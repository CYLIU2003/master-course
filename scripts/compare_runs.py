import json

with open('output/alns_best_effort.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
    
print('='*80)
print('拡張実行結果（600秒）')
print('='*80)
for row in data['rows']:
    print(f"\n{row['mode'].upper()}:")
    print(f"  Status: {row['solver_status']}")
    print(f"  Objective: {row['objective_value']:,.2f} JPY")
    print(f"  Served: {row['trip_count_served']}/{row['trip_count_served'] + row['trip_count_unserved']}")
    print(f"  Vehicles: {row['vehicle_count_used']}")
    print(f"  Time: {row['solve_time_seconds']:.1f}s")
    print(f"  Incumbents: {row['incumbent_history_count']}")
    
print('\n' + '='*80)
print('比較（300秒 vs 600秒）')
print('='*80)

# 300秒結果
with open('output/benchmark_final.json', 'r', encoding='utf-8') as f:
    short = json.load(f)
    alns_300 = [r for r in short['rows'] if r['mode'] == 'alns'][0]
    
# 600秒結果
alns_600 = [r for r in data['rows'] if r['mode'] == 'alns'][0]
    
print(f"\nALNS 300s: {alns_300['objective_value']:,.2f} JPY ({alns_300['incumbent_history_count']} incumbents)")
print(f"ALNS 600s: {alns_600['objective_value']:,.2f} JPY ({alns_600['incumbent_history_count']} incumbents)")
diff = alns_300['objective_value'] - alns_600['objective_value']
pct = (diff / alns_300['objective_value']) * 100
print(f"\n改善: {diff:,.2f} JPY ({pct:.3f}%)")

print('\n' + '='*80)
print('ALNS Incumbent履歴（600秒、最後10件）')
print('='*80)
for inc in alns_600['incumbent_history'][-10:]:
    status = "✓" if inc.get("feasible", False) else "✗"
    obj = inc['objective_value']
    iter_num = inc['iteration']
    print(f"{status} iter {iter_num:4d}: {obj:,.2f} JPY")
