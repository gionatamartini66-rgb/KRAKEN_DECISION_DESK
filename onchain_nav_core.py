"""KDD experimental chain-neutral evidence contract. No orders or account data."""
from dataclasses import dataclass, fields
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from types import MappingProxyType
from collections.abc import Mapping
import re

KINDS = frozenset({'FATTO_OSSERVATO', 'DATO_PROGRAMMATO', 'DATO_DERIVATO',
                   'INTERPRETAZIONE', 'IPOTESI_ECONOMICA', 'NON_DISPONIBILE'})


def utc(value):
    if not isinstance(value, str):
        raise ValueError('timestamp UTC assente')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('timestamp UTC invalido') from exc
    if result.tzinfo is None or result.utcoffset().total_seconds() != 0:
        raise ValueError('timestamp deve essere UTC esplicito')
    # Compare full precision: truncation wrongly rejects valid fractional seconds.
    if result > datetime.now(timezone.utc):
        raise ValueError('timestamp futuro')
    return result.isoformat().replace('+00:00', 'Z')


def uint(value, *, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not re.fullmatch(r'(0|[1-9][0-9]*)', str(value)):
        raise ValueError('quantita intera senza segno richiesta')
    n = int(value)
    if n > 2**64 - 1 or (n == 0 and not allow_zero):
        raise ValueError('quantita fuori intervallo')
    return n


def units(raw, places=9):
    n = uint(raw)
    return format(Decimal(n) / Decimal(10**places), 'f')


def _freeze(value):
    if isinstance(value, Mapping):
        if not all(isinstance(k, str) for k in value):
            raise ValueError('chiavi details non stringhe')
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(v) for v in value)
    if value is None or isinstance(value, (str, int, bool, float)):
        return value
    raise ValueError('valore details non serializzabile')


def _thaw(value):
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw(v) for v in value]
    return value


@dataclass(frozen=True)
class Observation:
    kind: str
    asset: str
    chain: str
    asset_id: str
    event: str
    quantity: str | None
    unit: str | None
    transaction: str | None
    block_reference: str | None
    event_utc: str | None
    acquired_utc: str
    reference_period: str | None
    knowable_utc: str | None
    source: str
    coverage: str
    verification: str
    limits: tuple[str, ...]
    compatible: tuple[str, ...]
    prohibited: tuple[str, ...]
    economic_relevance: str | None = None
    details: dict | None = None

    def __post_init__(self):
        if self.kind not in KINDS or not self.chain or not self.asset_id or not self.source:
            raise ValueError('contratto osservazione incompleto')
        acquired = datetime.fromisoformat(utc(self.acquired_utc).replace('Z', '+00:00'))
        event = datetime.fromisoformat(utc(self.event_utc).replace('Z', '+00:00')) if self.event_utc else None
        knowable = datetime.fromisoformat(utc(self.knowable_utc).replace('Z', '+00:00')) if self.knowable_utc else None
        if event and event > acquired:
            raise ValueError('evento successivo all acquisizione')
        if knowable and (knowable > acquired or (event and knowable < event)):
            raise ValueError('conoscibilita incompatibile con evidenza temporale')
        if self.quantity is not None:
            try:
                q = Decimal(self.quantity)
            except (InvalidOperation, TypeError) as exc:
                raise ValueError('quantita non numerica') from exc
            if not q.is_finite() or q <= 0 or not self.unit:
                raise ValueError('quantita non valida o unita assente')
        if self.kind == 'FATTO_OSSERVATO' and self.verification == 'VERIFICATO':
            if not (self.event_utc and self.transaction and self.block_reference):
                raise ValueError('fatto non tracciabile')
        for name in ('limits', 'compatible', 'prohibited'):
            seq = getattr(self, name)
            if not isinstance(seq, (tuple, list)) or not all(isinstance(s, str) for s in seq):
                raise ValueError(f'campo {name} non valido')
            object.__setattr__(self, name, tuple(seq))
        if self.details is not None:
            if not isinstance(self.details, Mapping):
                raise ValueError('details non dizionario')
            object.__setattr__(self, 'details', _freeze(self.details))

    def to_decision_context(self):
        """Detached JSON-compatible evidence; no BUY/SELL signal, score or forecast."""
        d = {f.name: _thaw(getattr(self, f.name)) for f in fields(self)}
        d['decision_status'] = 'CONTESTO_INFORMATIVO_NON_PREDITTIVO'
        d['knowability_status'] = ('DIMOSTRATA' if self.knowable_utc else 'NON_DETERMINABILE')
        return d
