import json, urllib.request
out=[]
for url in ('http://127.0.0.1:8000/api/app/context','http://127.0.0.1:8000/app/context'):
    try:
        data=urllib.request.urlopen(url,timeout=5).read().decode('utf-8')
        out.append({'url':url,'ok':True,'body':data[:500]})
    except Exception as e:
        out.append({'url':url,'ok':False,'error':str(e)})
open('tmp_api_check.json','w',encoding='utf-8').write(json.dumps(out,ensure_ascii=False,indent=2))
print('wrote tmp_api_check.json')
