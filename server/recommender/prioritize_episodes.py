"""Place explicitly selected series at the front of the background schedule queue."""
import json
import sys
from pathlib import Path

def prioritize(ids,root=Path(__file__).resolve().parent):
    path=root/'data'/'home-cache-config.json'
    config=json.loads(path.read_text()) if path.exists() else {}
    priority=list(dict.fromkeys([int(i) for i in ids]+config.get('episode_priority_ids',[])))
    if not all(i>0 for i in priority):raise ValueError('Positive Kinopoisk IDs required')
    config['episode_priority_ids']=priority
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.json.tmp');temporary.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
    temporary.replace(path)
    print('Episode queue priority:',priority)

if __name__=='__main__':prioritize(sys.argv[1:])
