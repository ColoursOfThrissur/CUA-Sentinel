import sqlite3
import json

con = sqlite3.connect('data/sentinel_core.db')
con.row_factory = sqlite3.Row
cur = con.cursor()

rows = cur.execute("SELECT id, attempt_id, tool_name, intent_payload, outcome_payload FROM side_effect_ledger WHERE attempt_id LIKE '%1794498966%'").fetchall()
for r in rows:
    print('=== ID:', r['id'], 'ATTEMPT:', r['attempt_id'], '===')
    intent = json.loads(r['intent_payload'])
    outcome = json.loads(r['outcome_payload']) if r['outcome_payload'] else {}
    print('EXIT CODE:', outcome.get('exit_code'))
    print('STDOUT:\n', outcome.get('stdout'))
    print('STDERR:\n', outcome.get('stderr'))
    script = intent.get('parameters', {}).get('script_code', '')
    print('SCRIPT PREVIEW:\n', '\n'.join(script.splitlines()[:25]))
    print('-' * 40)
