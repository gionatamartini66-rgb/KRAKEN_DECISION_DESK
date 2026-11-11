"""KDD experimental on-chain information contract. No trades, no account data."""
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
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
    if result > datetime.now(timezone.utc).replace(microsecond=0):
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
        utc(self.acquired_utc)
        if self.event_utc:
            utc(self.event_utc)
        if self.knowable_utc:
            utc(self.knowable_utc)
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

    def to_decision_context(self):
        """One-directional evidence interface: never emits a trading recommendation."""
        d = asdict(self)
        d['limits'] = list(self.limits)
        d['compatible'] = list(self.compatible)
        d['prohibited'] = list(self.prohibited)
        d['decision_status'] = 'CONTESTO_INFORMATIVO_NON_PREDITTIVO'
        return d
