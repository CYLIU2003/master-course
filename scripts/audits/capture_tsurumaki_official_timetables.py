"""Read-only browser audit of the three selected Tsurumaki route families.

Only rendered links and current snapshot references are followed. Sources are
cached with hashes; no timetable input is rewritten by this acquisition script.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import parse_qs, urljoin, urlparse


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.current = {**dict(attrs), 'text': ''}
            self.items.append(self.current)

    def handle_endtag(self, tag):
        if tag == 'a':
            self.current = None

    def handle_data(self, text):
        if self.current is not None:
            self.current['text'] += text


class BrowserAudit:
    def __init__(self, executable: str, session: str, output: Path):
        self.executable, self.session, self.output = executable, session, output
        self.output.mkdir(parents=True, exist_ok=True)
        self.counter = 0

    def command(self, *args: str) -> str:
        result = subprocess.run([self.executable, '--session', self.session, *args],
                                capture_output=True, text=True, encoding='utf-8', timeout=45)
        if result.returncode:
            raise RuntimeError(f'agent-browser {args[0]} failed: {result.stderr[:300]} {result.stdout[:300]}')
        return result.stdout

    def snapshot(self) -> str:
        text = self.command('snapshot', '-i')
        self.counter += 1
        (self.output / f'snapshot_{self.counter:04d}.txt').write_text(text, encoding='utf-8')
        return text

    def wait_snapshot(self, predicate) -> str:
        for _ in range(12):
            text = self.snapshot()
            if predicate(text):
                return text
            time.sleep(1)
        raise RuntimeError('Expected rendered navigation state did not appear')

    def click_text(self, label: str) -> None:
        snapshot = self.wait_snapshot(lambda text: bool(re.search(r'link "'+re.escape(label)+r'" \[ref=(e\d+)\]', text)))
        refs = re.findall(r'link "'+re.escape(label)+r'" \[ref=(e\d+)\]', snapshot)
        self.command('click', '@'+refs[0])
        # The official map closes its modal with a transition; the next link
        # can already exist underneath it while still being covered.
        time.sleep(1)
        self.snapshot()

    def capture(self, name: str, screenshot: bool = False) -> dict:
        script = '({url:location.href,title:document.title,text:document.body.innerText,html:document.documentElement.outerHTML})'
        payload = json.loads(self.command('--json', 'eval', script))
        if not payload.get('success'):
            raise RuntimeError('Browser DOM capture failed')
        result = payload['data']['result']
        result['retrieved_at_utc'] = datetime.now(timezone.utc).isoformat()
        result['html_sha256'] = hashlib.sha256(result['html'].encode()).hexdigest()
        result['browser_tool'] = 'agent-browser 0.37.1'
        (self.output / (name+'.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        if screenshot:
            self.command('screenshot', '--full', str((self.output / (name+'.png')).resolve()))
        return result

    def line_menu(self, line: str) -> str:
        self.command('open', 'https://transfer.navitime.biz/tokyubus/pc/map/Top?window=diagram')
        self.snapshot()
        self.click_text('系統から探す')
        self.click_text(line)
        return self.wait_snapshot(lambda text: '発 ' in text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser-executable', required=True)
    parser.add_argument('--session', default='seven-day-20260910')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fetch-trips', action='store_true')
    args = parser.parse_args()
    audit = BrowserAudit(args.browser_executable, args.session, args.output)
    known_diagrams = {}
    route_groups = []
    for line in ('渋２１', '渋２２', '渋２３'):
        snapshot = audit.line_menu(line)
        routes_page = audit.capture(line+'_route_list')
        variants = list(dict.fromkeys(re.findall(r'link "([^"\n]*発 [^"\n]*)" \[ref=e\d+\]', snapshot)))
        for index, variant in enumerate(variants):
            stem = f'{line}_{index:02d}'
            cached = args.output / (stem+'_diagram.json')
            if cached.exists():
                page = json.loads(cached.read_text(encoding='utf-8'))
                known_diagrams[page['url']] = page
                continue
            if index:
                audit.line_menu(line)
            audit.click_text(variant)
            stops = audit.wait_snapshot(lambda text: bool(re.search(r'cell "1 [^"\n]+"', text)))
            audit.capture(stem+'_stop_list')
            origin = re.search(r'cell "1 ([^"\n]+)"', stops)[1]
            audit.click_text(origin)
            audit.click_text('時刻表・のりば地図を見る')
            stop_map = audit.wait_snapshot(lambda text: '系統一覧' in text and 'ゆき' in text)
            page = audit.capture(stem+'_stop_map')
            links = Links()
            links.feed(page['html'])
            diagrams = [(a['text'].strip(), urljoin(page['url'], a.get('href',''))) for a in links.items
                        if 'BusDiagram?' in a.get('href','') and line in a['text']]
            if not diagrams:
                raise RuntimeError(f'No rendered diagram links for {line} at {origin}')
            for diagram_index, (label, url) in enumerate(diagrams):
                if url in known_diagrams:
                    page = known_diagrams[url]
                else:
                    audit.command('open', url)
                    audit.wait_snapshot(lambda text: 'columnheader "平日"' in text)
                    page = audit.capture(stem+f'_diagram_{diagram_index}', screenshot=True)
                    known_diagrams[url] = page
                if diagram_index == 0:
                    cached.write_text(json.dumps(page, ensure_ascii=False, indent=2), encoding='utf-8')
                route_groups.append({'line':line,'variant_label':variant,'origin':origin,'diagram_url':url})
            print(f'Captured {line}: {variant}', flush=True)
    jobs = {}
    for page in known_diagrams.values():
        links = Links()
        links.feed(page['html'])
        for link in links.items:
            url = urljoin(page['url'], link.get('href',''))
            if 'BusRouteTimetable?' not in url:
                continue
            query = parse_qs(urlparse(url).query)
            if query.get('stop-no') != ['1']:
                continue
            key = hashlib.sha256(url.encode()).hexdigest()[:20]
            jobs[key] = {'url':url,'source_diagram_url':page['url'],'label':link['text'].strip()}
    manifest = {'status':'DIAGRAMS_CAPTURED_TRIP_AUDIT_PENDING', 'route_groups':route_groups,
                'diagram_count':len(known_diagrams), 'trip_count':len(jobs), 'trips':jobs,
                'scope':'current_official_fixed_timetable_not_2025_historical_operations'}
    path = args.output / 'acquisition_manifest.json'
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.fetch_trips:
        for index, (key, item) in enumerate(jobs.items()):
            destination = args.output / ('trip_'+key+'.json')
            if not destination.exists():
                time.sleep(1)
                audit.command('open', item['url'])
                audit.wait_snapshot(lambda text: '停車時刻表' in text)
                audit.capture('trip_'+key)
            if index % 25 == 0:
                print(f'Trip sources {index+1}/{len(jobs)}', flush=True)
        manifest['status'] = 'SOURCES_CAPTURED_COMPARISON_PENDING'
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Diagrams={len(known_diagrams)}, first-stop trip links={len(jobs)}', flush=True)


if __name__ == '__main__':
    main()
