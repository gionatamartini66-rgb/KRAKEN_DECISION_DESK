// Execute this function in ChatGPT Work code mode with its existing tools.
// The revision must be the approved GitHub commit for the reader and bridge.
(async function recoverKddWithWork({tools, workspace, revision, folderTitle, pageSize = 100}) {
    const repository = "https://github.com/gionatamartini66-rgb/KRAKEN_DECISION_DESK.git";
    const quote = value => "'" + value.replaceAll("'", "'\\''") + "'";
    const trace = {inventari: [], download: 0, letture_puntuali: 0, esiti_filtri: []};

    function payload(result) {
        if (result.isError || !result.structuredContent) {
            throw new Error("OPERAZIONE_CONNETTORE_NON_DISPONIBILE");
        }
        return result.structuredContent;
    }

    async function shell(cmd, options = {}) {
        let result = await tools.exec_command({cmd, workdir: workspace, ...options});
        let output = result.output;
        while (result.session_id !== undefined) {
            result = await tools.write_stdin({session_id: result.session_id, chars: "", yield_time_ms: 1000});
            output += result.output;
        }
        return {code: result.exit_code, output};
    }

    async function writeJson(path, object) {
        const serialized = JSON.stringify(object).replace(/[^\x00-\x7F]/g, character =>
            "\\u" + character.charCodeAt(0).toString(16).padStart(4, "0"));
        // Keep each shell argument below the per-argument OS limit, including
        // when a full inventory comprises many metadata pages.
        for (let offset = 0; offset < serialized.length; offset += 16000) {
            const result = await shell("umask 077 && printf '%s' " +
                quote(serialized.slice(offset, offset + 16000)) +
                (offset ? " >> " : " > ") + quote(path));
            if (result.code !== 0) throw new Error("CATTURA_NON_SCRIVIBILE");
        }
    }

    try {
        if (!/^[0-9a-f]{40}$/.test(revision)) throw new Error("REVISIONE_GITHUB_NON_IDENTIFICATA");
        const folders = payload(await tools.mcp__codex_apps__google_drive_search({
            query: folderTitle, item_type: "folder", best_effort_fetch: false, topn: 100
        }));
        const matches = folders.results.filter(row => row.title === folderTitle);
        if (folders.next_page_token || matches.length !== 1) {
            throw new Error("CARTELLA_CONNETTORE_ASSENTE_O_AMBIGUA");
        }
        const folder = matches[0];
        if (!/^[A-Za-z0-9_-]{6,128}$/.test(folder.id)) throw new Error("CARTELLA_NON_VALIDA");

        const setup = await shell("umask 077 && mktemp -d " + quote(workspace + "/kdd-drive-work.XXXXXXXX"));
        if (setup.code !== 0) throw new Error("AMBIENTE_LOCALE_NON_DISPONIBILE");
        const directory = setup.output.trim();
        const checkout = quote(directory + "/repo");
        const capture = directory + "/capture";
        const initialized = await shell("umask 077 && git init -q " + checkout +
            " && git -C " + checkout + " fetch -q --depth=1 " + quote(repository) + " " + quote(revision) +
            " && test \"$(git -C " + checkout + " rev-parse FETCH_HEAD)\" = " + quote(revision) +
            " && git -C " + checkout + " checkout -q --detach FETCH_HEAD" +
            " && mkdir -p " + ["blobs", "prima-prove", "dopo-prove"].map(name => quote(capture + "/" + name)).join(" "));
        if (initialized.code !== 0) throw new Error("CHECKOUT_GITHUB_NON_DISPONIBILE");
        trace.revisione = revision;

        async function run(action) {
            const result = await shell("cd " + checkout + " && PYTHONPATH=.:scripts python -S -B -m " +
                "scripts.kdd_drive_connector " + action + " " + quote(folder.id) + " " + quote(capture));
            if (![0, 2].includes(result.code)) throw new Error("PYTHON_KDD_NON_ESEGUIBILE");
            try { return JSON.parse(result.output); } catch { throw new Error("RISPOSTA_PYTHON_KDD_INVALIDA"); }
        }

        async function inventory(phase) {
            const pages = [];
            const used = new Set();
            let token = null;
            let fileCount = 0;
            do {
                const result = payload(await tools.mcp__codex_apps__google_drive_list_folder_page({
                    url: "https://drive.google.com/drive/folders/" + folder.id,
                    page_token: token, page_size: pageSize
                }));
                if (!Array.isArray(result.files)) throw new Error("PAGINA_CONNETTORE_INVALIDA");
                pages.push({requested_page_token: token, response: result});
                fileCount += result.files.length;
                token = result.next_page_token ?? null;
                if (token !== null && (typeof token !== "string" || !token || used.has(token) ||
                                       pages.length >= 80 || fileCount > 10000)) {
                    throw new Error("LIMITE_O_CURSORE_CONNETTORE");
                }
                used.add(token);
            } while (token !== null);
            trace.inventari.push({fase: phase, pagine: pages.length, file: fileCount});
            await writeJson(capture + "/" + phase + ".json", {folder_id: folder.id, pages});
        }

        async function attest(phase, files) {
            for (const file of files) {
                const metadata = payload(await tools.mcp__codex_apps__google_drive_get_file_metadata({
                    fileId: file.id, fields: file.fields
                }));
                trace.letture_puntuali++;
                const receipt = {metadata};
                if (metadata.trashed == null || (metadata.parent_ids ?? metadata.parents) == null) {
                    const result = payload(await tools.mcp__codex_apps__google_drive_search({
                        special_filter_query_str: file.query, best_effort_fetch: false, topn: 8
                    }));
                    receipt.search = {query: file.query, results: result.results};
                    trace.esiti_filtri.push(result.results.filter(row => row.id === file.id).length);
                }
                await writeJson(capture + "/" + phase + "-prove/" + file.id + ".json", receipt);
            }
        }

        async function download(file) {
            const result = payload(await tools.mcp__codex_apps__google_drive_fetch({
                url: "https://drive.google.com/file/d/" + file.id,
                download_raw_file: true, include_base64: false
            }));
            if (result.id !== file.id || result.file_size_bytes !== file.dimensione_byte || !result.file_uri) {
                throw new Error("RIFERIMENTO_RAW_NON_VERIFICABILE");
            }
            const transfer = {uri: result.file_uri, path: capture + "/blobs/" + file.id, size: file.dimensione_byte};
            const python = `import json, sys, urllib.request
from pathlib import Path
from urllib.parse import urlsplit
data = json.load(sys.stdin)
ref = data["uri"]
size = data["size"]
try:
    if ref.get("workspace_path"):
        with open(ref["workspace_path"], "rb") as stream:
            raw = stream.read(size + 1)
    else:
        url = ref["download_url"]
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname.endswith(".oaiusercontent.com"):
            raise ValueError
        with urllib.request.urlopen(url, timeout=15) as stream:
            raw = stream.read(size + 1)
    if len(raw) != size:
        raise ValueError
    Path(data["path"]).write_bytes(raw)
except Exception:
    raise SystemExit(2)`;
            const saved = await shell("umask 077 && printf '%s' " + quote(JSON.stringify(transfer)) +
                                      " | python -S -B -c " + quote(python));
            if (saved.code !== 0) throw new Error("BYTE_RAW_NON_MATERIALIZZABILI_IN_PYTHON");
            trace.download++;
        }

        await inventory("prima");
        const requested = await run("select");
        if (requested.stato !== "PIANO_PROVE") return {result: requested, trace};
        await attest("prima", requested.file);
        const plan = await run("plan");
        if (plan.stato !== "PIANO_DOWNLOAD") return {result: plan, trace};
        for (const file of plan.file) await download(file);
        await inventory("dopo");
        await attest("dopo", requested.file);
        return {result: await run("validate"), trace};
    } catch (error) {
        const code = /^[A-Z0-9_]+$/.test(error.message) ? error.message : "PASSAGGIO_CONNETTORE_PYTHON_NON_VERIFICABILE";
        return {result: {stato: "DOSSIER_NON_VERIFICABILE", codice: code}, trace};
    }
})
