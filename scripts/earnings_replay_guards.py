"""Fail closed on unverified phase transitions."""
from pathlib import Path
import hashlib,json


def require_closed_normal(directory):
    directory=Path(directory)
    closure=json.loads((directory/'closure.json').read_text())
    if closure.get('status')!='EARNINGS_ACCOUNTED_PACKET_CLOSED':
        raise ValueError('Normal arm not independently accounted and packet closed')
    evidence=closure.get('evidence',{})
    if set(evidence)!={'independent_audit','trial_packet'}:
        raise ValueError('Exact audit and trial packet bindings required')
    loaded={}
    for key,binding in evidence.items():
        path=Path(binding['path'])
        if not path.is_absolute():path=directory/path
        if hashlib.sha256(path.read_bytes()).hexdigest()!=binding['sha256']:
            raise ValueError('Closure evidence changed')
        loaded[key]=json.loads(path.read_text())
    if loaded['independent_audit'].get('pass') is not True:
        raise ValueError('Independent accounting audit must pass')
    # Full trial packet schema validation remains the closer's responsibility.
    if not loaded['trial_packet']:
        raise ValueError('Empty trial packet')
    return closure
