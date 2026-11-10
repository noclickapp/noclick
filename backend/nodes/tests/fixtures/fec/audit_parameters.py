"""Supplement the unchanged harness verdict when broken security masks parameter validation.

Calls the original contract's parameter and body validators directly. Never
changes security, the published spec, a request, or the harness verdict.
"""
import json
import sys
from pathlib import Path
import httpx
from tests.conformance.harness import Contract
c=Path(sys.argv[1])
contract=Contract(json.loads((c/'openapi3.json').read_text()),server_url='https://api.open.fec.gov')
out=[]
for op in json.loads((c/'report.json').read_text())[0]['operations']:
 for r in op['requests']:
  req=httpx.Request(r['method'],r['url'],headers=r['headers'],content=r.get('body','').encode())
  adapter=contract.adapter(req)
  path,operation,_,_,_=contract.api.request_validator._find_path(adapter)
  try: contract.api.request_validator._get_parameters(adapter.parameters,operation,path)
  except Exception as exc:
   print(op['operation'], [str(x) for x in getattr(exc, 'errors', [exc])]); continue
  if adapter.body: contract.api.request_validator._get_body(adapter.body,adapter.content_type,operation)
  out.append({'operation':op['operation'],'contract_operation':r['spec_operation'],'parameters_and_body_valid':True})
assert len(out)==21
(c/'parameter-audit.json').write_text(json.dumps({'note':'Supplement only. The unmodified main report still blocks on the provider security contradiction. No security override or contract repair used.','requests_checked':len(out),'checks':out},indent=2)+'\n')
print('Parameter/body validation passed for',len(out),'recorded requests against the unchanged converted contract')
