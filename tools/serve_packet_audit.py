"""Serve the existing dashboard plus an authenticated, read-only packet audit.

Lives outside the bound host package: no started-game contract migration.
"""
import argparse
import csv
import io
import os
from pathlib import Path
import re
import sys
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse
import zipfile
from edh_gauntlet.dashboard import Dashboard, Handler

PAGE = r'''<!doctype html><meta charset="utf-8"><title>Reaminatour packet audit</title>
<style>body{font:16px system-ui;margin:2rem;color:#17202a}input,button{font:inherit;padding:.4rem}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f6fa;padding:1rem}a{margin-right:1rem}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}#error{color:#a00}</style>
<a href="/">Game dashboard</a><h1>Reaminatour · game O packet audit</h1>
<label>Authorization key <input id="key" type="password"></label><button id="connect">Connect / refresh</button><p id="error"></p><p id="status"></p>
<p id="links"></p><p>Round membership and board columns follow the snapshot delivered to the role; a planner's output may arrive after live play has moved on. Length is UTF-8 bytes of the recorded JSON. Opening/setup is included with round 1.</p>
<div id="content"></div><script>
const $=x=>document.querySelector(x);$('#key').value=sessionStorage.edhKey||'';
async function api(name){const r=await fetch('/api/packet-audit/'+name,{headers:{Authorization:'Bearer '+$('#key').value}});if(!r.ok)throw Error('Request failed: '+r.status);return r}
function a(text,fn){const x=document.createElement('a');x.href='#';x.textContent=text;x.onclick=e=>{e.preventDefault();fn().catch(error=>$('#error').textContent=error.message)};return x}
async function download(name){const r=await api(name),u=URL.createObjectURL(await r.blob()),x=document.createElement('a');x.href=u;x.download=name;x.click();setTimeout(()=>URL.revokeObjectURL(u),1000)}
async function packet(id){if(!/^(?:[a-f0-9]{24}|help-\d+)$/.test(id))throw Error('Invalid packet');const raw=await(await api('packets/'+id+'.html')).text();const doc=new DOMParser().parseFromString(raw,'text/html');const container=$('#content');container.replaceChildren();const back=a('Back to rounds',async()=>{location.hash='';await render()});container.append(back);const prev=[...doc.querySelectorAll('a')].find(x=>x.textContent.startsWith('Previous'));if(prev){const pid=prev.getAttribute('href').replace('.html','');container.append(a('Previous packet in this role conversation',async()=>{location.hash='packet='+pid}))}const button=document.createElement('button');button.textContent='Copy packet';button.onclick=()=>navigator.clipboard.writeText(doc.querySelector('pre').textContent);const pre=document.createElement('pre');pre.textContent=doc.querySelector('pre').textContent;container.append(button,pre)}
async function render(){sessionStorage.edhKey=$('#key').value;$('#error').textContent='';const m=await(await api('manifest.json')).json();$('#status').textContent='Turn '+m.latest_turn+' · accepted prefix '+m.accepted_prefix.sequence+' · updated '+m.updated_utc+' · '+m.decode_errors.length+' decoding gaps';const links=$('#links');links.replaceChildren();for(const n of [1,5,7])links.append(a('Round '+n+' CSV ('+m.rounds[n].rows+' rows; '+m.rounds[n].status+')',()=>download('round-'+n+'.csv')));links.append(a('Download all CSVs + packet copies (ZIP)',()=>download('bundle.zip')));if(location.hash.startsWith('#packet=')){await packet(location.hash.slice(8));return}const pre=document.createElement('pre');pre.textContent=await(await api('README.md')).text();$('#content').replaceChildren(pre)}
$('#connect').onclick=()=>render().catch(e=>$('#error').textContent=e.message);window.onhashchange=$('#connect').onclick;if($('#key').value)$('#connect').click();
</script>'''


class AuditHandler(Handler):
    def do_GET(self):
        path=urlparse(self.path).path
        if path in ('/audit','/audit/'):
            return self.send_value(PAGE,content_type='text/html; charset=utf-8')
        if path.startswith('/api/packet-audit/'):
            if not self.auth():return self.send_value({'error':'unauthorized'},401)
            name=path.removeprefix('/api/packet-audit/')
            allowed=re.fullmatch(r'(round-(1|5|7)\.csv|manifest\.json|README\.md|bundle\.zip|packets/([a-f0-9]{24}|help-\d+)\.html)',name)
            if not allowed:return self.send_value({'error':'not found'},404)
            root=self.server.audit
            if name=='bundle.zip':
                data=io.BytesIO()
                with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as archive:
                    for file in sorted(root.rglob('*')):
                        if file.is_file() and (file.suffix in ('.csv','.html','.md') or file.name=='manifest.json'):
                            archive.write(file,file.relative_to(root))
                return self.send_value(data.getvalue(),content_type='application/zip')
            file=root/name
            if not file.is_file():return self.send_value({'error':'not ready'},404)
            if name.endswith('.csv'):
                rows=list(csv.reader(io.StringIO(file.read_text(encoding='utf8'))))
                if rows:
                    link=rows[0].index('hyperlink to copy');identity=rows[0].index('record ID')
                    for row in rows[1:]:
                        if re.fullmatch(r'[a-f0-9]{24}|help-\d+',row[identity]):
                            row[link]='=HYPERLINK("'+self.server.public_url+'/audit/#packet='+row[identity]+'","Open packet")'
                stream=io.StringIO();csv.writer(stream).writerows(rows)
                return self.send_value(stream.getvalue(),content_type='text/csv; charset=utf-8')
            content_type={'.csv':'text/csv; charset=utf-8','.json':'application/json; charset=utf-8','.md':'text/plain; charset=utf-8','.html':'text/html; charset=utf-8'}[file.suffix]
            return self.send_value(file.read_bytes(),content_type=content_type)
        return super().do_GET()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runs',type=Path,required=True);p.add_argument('--audit',type=Path,required=True)
    p.add_argument('--host',default='0.0.0.0');p.add_argument('--port',type=int,default=8765)
    p.add_argument('--public-url',required=True)
    args=p.parse_args()
    server=ThreadingHTTPServer((args.host,args.port),AuditHandler)
    server.app=Dashboard(args.runs,os.environ['EDH_DASHBOARD_KEY'],sys.executable)
    server.audit=args.audit.resolve()
    server.public_url=args.public_url.rstrip('/')
    server.serve_forever()


if __name__=='__main__':main()
