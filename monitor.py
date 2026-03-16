import json, time, os

def get_most_recent_job():
    jobs_dir = "outputs/jobs"
    if not os.path.exists(jobs_dir): return None
    files = [os.path.join(jobs_dir, f) for f in os.listdir(jobs_dir) if f.endswith(".json")]
    if not files: return None
    most_recent = max(files, key=os.path.getmtime)
    with open(most_recent, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return None

while True:
    job = get_most_recent_job()
    if job:
        print(f"Job: {job.get('job_id')} - Status: {job.get('status')} - Progress: {job.get('progress')}% - {job.get('message')}")
        if job.get('status') in ['completed', 'failed']:
            if job.get('status') == 'failed':
                print(f"Error: {job.get('error')}")
            break
    time.sleep(5)
