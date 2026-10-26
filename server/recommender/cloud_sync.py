"""Personal record synchronization. Immutable LWW records retain deletions.

No catalog refresh timestamps, recommendation scores or local profile revisions
participate in change detection. Independent servers merge all unseen versions.
"""
import copy
import hashlib
import json
import time

OWNER = '@owner'
KEYS = {
 'profiles': ('profile_id',), 'home_profiles': ('profile_id',),
 'rating_scale': ('profile_id','rating'), 'user_ratings': ('profile_id','kp_id'),
 'watchlist': ('profile_id','kp_id'), 'recommendation_feedback': ('profile_id','kp_id'),
 'track_preferences': ('profile_id','series_key','kind'), 'home_connections': ('profile_id',),
 'series_tracking': ('profile_id','kp_id'),
}
VOLATILE = {'created_at','updated_at','checked_at','error'}
FAVORITE_CATEGORIES = ('card','like','wath','book','history','look','viewed','scheduled','continued','thrown')


def encoded(value):
 return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':'))


def digest(records):
 return hashlib.sha256(encoded(records).encode()).hexdigest()


def rows(document, name):
 table=document.get('tables',{}).get(name)
 if not table:return []
 return [dict(zip(table['columns'], row)) for row in table['rows']]


def project(document):
 from profiles import FIELDS
 owner=document['owner']; result={}
 def ident(p):return OWNER if p==owner else p
 def put(path,value):result[encoded(path)]=copy.deepcopy(value)
 for table,pk in KEYS.items():
  for row in rows(document,table):
   row['profile_id']=ident(row['profile_id'])
   if table=='series_tracking':row={k:row[k] for k in (*pk,'tracking_mode')}
   else:row={k:v for k,v in row.items() if k not in VOLATILE}
   put(['row',table,[row[k] for k in pk]], row)
 for row in rows(document,'home_profile_state'):
  profile=ident(row['profile_id']); values=json.loads(row['document'])
  put(['state',profile],{})
  for field,value in values.items():
   if field not in FIELDS or field=='timetable':continue
   path=['state',profile,field]
   if isinstance(value,dict):
    put(path,{'kind':'map'})
    entries = {key:[] for key in FAVORITE_CATEGORIES} if field=='favorite' else {}
    entries.update(value)
    for key,entry in entries.items():
     if field=='favorite' and isinstance(entry,list):
      put(path+[key],{'kind':'members'})
      for rank,item in enumerate(entry):
       item_id=encoded(item.get('id')) if key=='card' and isinstance(item,dict) else encoded(item)
       put(path+[key,item_id],{'item':item,'rank':rank})
     else:put(path+[key],entry)
   else:put(path,{'kind':'value','value':value})
 for device,row in document.get('devices',{}).items():
  for field,value in row['values'].items():put(['device',device,field],value)
 return result


def validate(records):
 if not isinstance(records,dict) or len(records)>200000:raise ValueError('Invalid sync records')
 from profiles import FIELDS
 from cloud_disk import DEVICE_FIELDS
 for key,record in records.items():
  path=json.loads(key)
  if not isinstance(path,list) or not path:raise ValueError('Invalid sync path')
  kind=path[0]
  if kind=='row':
   if len(path)!=3 or path[1] not in KEYS or not isinstance(path[2],list) or len(path[2])!=len(KEYS[path[1]]):raise ValueError('Invalid row key')
  elif kind=='state':
   if not 2<=len(path)<=5 or not isinstance(path[1],str) or (len(path)>2 and path[2] not in FIELDS):raise ValueError('Invalid state key')
  elif kind=='device':
   if len(path)!=3 or path[2] not in DEVICE_FIELDS:raise ValueError('Invalid device key')
  else:raise ValueError('Unsupported sync record')
  if not isinstance(record,dict) or set(record)!={'clock','deleted','value'}:raise ValueError('Invalid sync record')
  clock=record['clock']
  if not isinstance(clock,list) or len(clock)!=3 or type(clock[0]) is not int or type(clock[1]) is not int or not isinstance(clock[2],str) or not isinstance(record['deleted'],bool):raise ValueError('Invalid sync clock')
 return records


def join(*states):
 result={}
 for state in states:
  validate(state)
  for key,record in state.items():
   old=result.get(key)
   if old is None or (record['clock'],encoded(record))>(old['clock'],encoded(old)):
    result[key]=copy.deepcopy(record)
 return result


def observe(records, previous, current, actor, counter, now=None):
 result=copy.deepcopy(records);now=int(time.time()*1000) if now is None else now
 for key in previous.keys()|current.keys():
  if key in previous and key in current and previous[key]==current[key]:continue
  deleted=key not in current;value=current.get(key)
  old=result.get(key)
  if old and old['deleted']==deleted and (deleted or old['value']==value):continue
  counter+=1;clock=now
  path=json.loads(key)
  if len(path)==4 and path[0]=='state' and path[2] in ('file_view','online_watched_last') and isinstance(value,dict):
   clock=int(value.get('_hc_updated') or value.get('updated') or now)
  candidate={'clock':[clock,counter,actor],'deleted':deleted,'value':value}
  # A stale TV timeline must not overwrite a record with a newer viewing clock.
  old=result.get(key)
  if old is None or candidate['clock']>old['clock']:result[key]=candidate
 return result,counter


def materialize(records):
 validate(records)
 states={};devices={};table_rows={name:[] for name in KEYS};children={}
 for key,record in records.items():
  if record['deleted']:continue
  path=json.loads(key);value=record['value']
  children.setdefault(encoded(path[:-1]),[]).append((key,path,value))
  if path[0]=='row':table_rows[path[1]].append((path[2],value))
  elif path[0]=='device':
   row=devices.setdefault(path[1],{'values':{},'updated_at':0})
   row['values'][path[2]]=value
   row['updated_at']=max(row['updated_at'],record['clock'][0]//1000)
  elif len(path)==2:states.setdefault(path[1],{})
 for profile,values in states.items():
  for _,path,marker in children.get(encoded(['state',profile]),[]):
   if not isinstance(marker,dict):raise ValueError('Invalid state marker')
   if marker.get('kind')=='value':values[path[2]]=marker['value'];continue
   if marker.get('kind')!='map':raise ValueError('Invalid map marker')
   target={};values[path[2]]=target
   for _,child,value in children.get(encoded(path),[]):
    if path[2]=='favorite' and isinstance(value,dict) and value.get('kind')=='members':
     members=children.get(encoded(child),[])
     for _,_,entry in members:
      if not isinstance(entry,dict) or type(entry.get('rank')) is not int or 'item' not in entry:
       raise ValueError('Invalid favorite member')
     members=sorted(members,key=lambda item:(item[2]['rank'],-records[item[0]]['clock'][0],-records[item[0]]['clock'][1],records[item[0]]['clock'][2]))
     target[child[3]]=[entry['item'] for _,_,entry in members]
    else:target[child[3]]=value
 return table_rows,states,devices


def apply(connection, owner, records, documents):
 """Called inside the caller's BEGIN IMMEDIATE; does not commit or reset epochs."""
 from profiles import safe_values
 table_rows,states,devices=materialize(records)
 def local(value):return owner if value==OWNER else value
 # Metadata is only a dependency for personal ratings/lists, not a sync trigger.
 columns=[r[1] for r in connection.execute('PRAGMA table_info(media)')]
 media_seen=set()
 for document in documents:
  for row in rows(document,'media'):
   if row.get('kp_id') in media_seen:continue
   media_seen.add(row.get('kp_id'))
   if set(row)==set(columns):
    connection.execute('INSERT OR IGNORE INTO media ('+','.join('"'+c+'"' for c in columns)+') VALUES('+','.join('?' for _ in columns)+')',[row[c] for c in columns])
 existing={r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 # Only explicit tombstones delete data. Absence from an older snapshot never does.
 for name in reversed(KEYS):
  if name not in existing:continue
  pk=KEYS[name]
  for key,record in records.items():
   path=json.loads(key)
   if path[:2]!=['row',name] or not record['deleted']:continue
   if name=='profiles' and path[2]==[OWNER]:raise ValueError('Cannot remove owner')
   connection.execute('DELETE FROM "'+name+'" WHERE '+' AND '.join('"'+k+'"=?' for k in pk),[local(v) if k=='profile_id' else v for k,v in zip(pk,path[2])])
 for name,items in table_rows.items():
  if name not in existing and items:raise ValueError('Missing local sync table: '+name)
  columns={r[1]:r for r in connection.execute('PRAGMA table_info("'+name+'")')};pk=KEYS[name]
  for identity,row in items:
   if not isinstance(row,dict) or set(row)-set(columns):raise ValueError('Unsupported sync row: '+name)
   if any(row.get(k)!=v for k,v in zip(pk,identity)):raise ValueError('Mismatched sync identity')
   row=dict(row);row['profile_id']=local(row['profile_id'])
   where=' AND '.join('"'+k+'"=?' for k in pk);ids=[row[k] for k in pk]
   old=connection.execute('SELECT * FROM "'+name+'" WHERE '+where,ids).fetchone()
   if old:
    current=dict(old)
    if all(current[k]==v for k,v in row.items()):continue
    fields=[k for k in row if k not in pk]
    connection.execute('UPDATE "'+name+'" SET '+','.join('"'+k+'"=?' for k in fields)+' WHERE '+where,[row[k] for k in fields]+ids)
   else:
    for col,info in columns.items():
     if col not in row and info[3] and info[4] is None:
      row[col]=0 if 'INT' in info[2].upper() else ''
    fields=list(row)
    connection.execute('INSERT INTO "'+name+'" ('+','.join('"'+k+'"' for k in fields)+') VALUES('+','.join('?' for _ in fields)+')',[row[k] for k in fields])
 for profile,values in states.items():
  profile=local(profile);values=safe_values(values)
  current=connection.execute('SELECT revision,document FROM home_profile_state WHERE profile_id=?',(profile,)).fetchone()
  if current and json.loads(current['document'])==values:continue
  connection.execute('INSERT OR REPLACE INTO home_profile_state VALUES(?,?,?,?)',(profile,(current['revision'] if current else 0)+1,encoded(values),int(time.time())))
 return devices
