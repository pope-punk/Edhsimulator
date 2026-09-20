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

PAGE = Path(__file__).with_name('packet_audit.html').read_text(encoding='utf8')


class AuditHandler(Handler):
    def do_GET(self):
        path=urlparse(self.path).path
        if path in ('/audit','/audit/'):
            return self.send_value(PAGE,content_type='text/html; charset=utf-8')
        if path.startswith('/api/packet-audit/'):
            if not self.auth():return self.send_value({'error':'unauthorized'},401)
            name=path.removeprefix('/api/packet-audit/')
            allowed=re.fullmatch(r'(round-(1|5|7)\.(csv|json)|manifest\.json|README\.md|bundle\.zip|packets/([a-f0-9]{24}|help-\d+)\.html)',name)
            if not allowed:return self.send_value({'error':'not found'},404)
            root=self.server.audit
            if name=='bundle.zip':
                data=io.BytesIO()
                with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as archive:
                    for file in sorted(root.rglob('*')):
                        if file.is_file() and (file.suffix in ('.csv','.html','.md') or file.name=='manifest.json'):
                            archive.write(file,file.relative_to(root))
                return self.send_value(data.getvalue(),content_type='application/zip')
            if re.fullmatch(r'round-(1|5|7)\.json',name):
                source=root/name.replace('.json','.csv')
                if not source.is_file():return self.send_value({'error':'not ready'},404)
                with source.open(newline='',encoding='utf8') as stream:
                    rows=list(csv.DictReader(stream))
                return self.send_value({'rows':rows})
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
