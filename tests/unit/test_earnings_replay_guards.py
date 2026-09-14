import json,hashlib
import pytest
from earnings_replay_guards import require_closed_normal

def test_missing_empty_or_modified_closure_refused(tmp_path):
 with pytest.raises(FileNotFoundError):require_closed_normal(tmp_path)
 (tmp_path/'closure.json').write_text('{}')
 with pytest.raises(ValueError):require_closed_normal(tmp_path)
 audit=tmp_path/'audit.json';audit.write_text('{"pass":true}')
 packet=tmp_path/'packet.json';packet.write_text('{"id":"synthetic"}')
 closure={'status':'EARNINGS_ACCOUNTED_PACKET_CLOSED','evidence':{k:{'path':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for k,p in [('independent_audit',audit),('trial_packet',packet)]}}
 (tmp_path/'closure.json').write_text(json.dumps(closure))
 require_closed_normal(tmp_path)
 audit.write_text('{"pass":false}')
 with pytest.raises(ValueError):require_closed_normal(tmp_path)
