# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import argparse
import datetime
import jsone
import os
import slugid
import taskcluster
import yaml

from git import Repo
from lib.tasks import schedule_task

ROOT = os.path.join(os.path.dirname(__file__), '../..')


def calculate_git_references(root):
    repo = Repo(root)
    remote = repo.remote()
    branch = repo.head.reference

    assert remote.url.startswith('https://github.com'), 'expected remote to be a GitHub repository (accessed via HTTPs)'
    url = remote.url[:-4] if remote.url.endswith('.git') else remote.url

    return url, str(branch), str(branch.commit)


def make_decision_task(params):
    """Generate a basic decision task, based on the root .taskcluster.yml"""
    with open(os.path.join(ROOT, '.taskcluster.yml'), 'rb') as f:
        taskcluster_yml = yaml.safe_load(f)

    slugids = {}

    def as_slugid(name):
        if name not in slugids:
            slugids[name] = slugid.nice()
        return slugids[name]

    # provide a similar JSON-e context to what taskcluster-github provides
    context = {
        'tasks_for': 'cron',
        'cron': {
            'task_id': params['cron_task_id']
        },
        'now': datetime.datetime.utcnow().isoformat()[:23] + 'Z',
        'as_slugid': as_slugid,
        'command_staging_flag': '--staging' if params['is_staging'] else '',
        'route_environment': 'staging-nightly' if params['is_staging'] else 'nightly',
        'signing_environment': 'dep-signing' if params['is_staging'] else 'release-signing',
        'pushapk_environment': ':dep' if params['is_staging'] else '',
        'scriptworker_environment': '-dep' if params['is_staging'] else '',
        'event': {
            'repository': {
                'clone_url': params['repository_github_http_url']
            },
            'release': {
                'tag_name': params['head_rev'],
                'target_commitish': params['branch']
            },
            'sender': {
                'login': 'TaskclusterHook'
            }
        }
    }

    rendered = jsone.render(taskcluster_yml, context)
    if len(rendered['tasks']) != 1:
        raise Exception('Expected .taskcluster.yml to only produce one cron task')
    task = rendered['tasks'][0]

    task_id = task.pop('taskId')
    return task_id, task


def schedule(is_staging):
    queue = taskcluster.Queue({'baseUrl': 'http://taskcluster/queue/v1'})

    repository_github_http_url, branch, head_rev = calculate_git_references(ROOT)
    params = {
        'is_staging': is_staging,
        'repository_github_http_url': repository_github_http_url,
        'head_rev': head_rev,
        'branch': branch,
        'cron_task_id': os.environ.get('CRON_TASK_ID', '<cron_task_id>')
    }
    decision_task_id, decision_task = make_decision_task(params)
    schedule_task(queue, decision_task_id, decision_task)
    print('All scheduled!')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Schedule a nightly release pipeline')

    parser.add_argument('--staging', action='store_true',
                        help="Perform a staging build (use dep workers, don't communicate with Google Play) ")

    result = parser.parse_args()
    schedule(result.staging)