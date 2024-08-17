# pytest-scrutinize

![PyPI - Version](https://img.shields.io/pypi/v/pytest-scrutinize) ![PyPI - Python Version](https://img.shields.io/pypi/pyversions/pytest-scrutinize) ![PyPI - Status](https://img.shields.io/pypi/status/pytest-scrutinize) ![PyPI - Format](https://img.shields.io/pypi/format/pytest-scrutinize) ![PyPI - License](https://img.shields.io/pypi/l/pytest-scrutinize)

Big test suites for large projects can be a pain to optimize. `pytest-scrutinize` helps you
profile your test runs by exporting *detailed* timings as JSON for the following things:

- Tests
- [Fixture setup/teardowns](#fixture-setup-and-teardown)
- [Django SQL queries](#django-sql-queries)
- [pytest-xdist](https://pypi.org/project/pytest-xdist/) worker boot times
- [Arbitrary functions](#record-additional-functions-)
- [Garbage collections](#garbage-collection)
- Pytest setup/collection times

All data is associated with the currently executing test or fixture. As an example, you can
use this to find all the Django SQL queries executed within a given fixture across your
entire test suite.

## Installation:

Install with pip [from PyPI](https://pypi.org/project/pytest-scrutinize/)

```
pip install pytest-scrutinize
```

## Usage:

Run your test suite with the `--scrutinize` flag, passing a file path to write to:

```
pytest --scrutinize=tests.jsonl.gz
```

## Analysing the results


A tool to help with analysing this data is not included yet, however it can be quickly explored 
with [DuckDB](https://duckdb.org/). For example, to find the top 10 fixtures by total duration 
along with the number of tests that where executed:

```sql
select name,
       to_microseconds(sum(runtime.as_microseconds)::bigint) as duration,
       count(distinct test_id) as test_count
from 'test-timings.jsonl'
where type = 'fixture'
group by all
order by duration desc
limit 10;
```

Or the tests with the highest number of duplicated SQL queries executed as part of it or 
any fixture it depends on:

```sql
select test_id,
       sum(count)               as duplicate_queries,
       count(distinct sql_hash) as unique_queries,
FROM (SELECT test_id, fixture_name, sql_hash, COUNT(*) AS count
      from 'test-timings.jsonl'
      where type = 'django-sql'
      GROUP BY all
      HAVING count > 1)
group by all
order by duplicate_queries desc limit 10;
```

## Data captured:

The resulting file will contain newline-delimited JSON objects. The Pydantic models for these 
can be [found here](./pytest_scrutinize/data.py).

All events captured contain a `meta` structure that contains the `xdist` worker (if any), the 
absolute time the timing was taken and the Python thread name that the timing was captured in.

<details>
<summary>Meta example</summary>

```json
{
  "meta": {
    "worker": "gw0",
    "recorded_at": "2024-08-17T22:02:44.956924Z",
    "thread_id": 3806124,
    "thread_name": "MainThread"
  }
}
```

</details>

All durations are expressed with the same structure, containing the duration in different formats: 
nanoseconds, microseconds, ISO 8601 and text

<details>
<summary>Duration example</summary>

```json
{
  "runtime": {
    "as_nanoseconds": 60708,
    "as_microseconds": 60,
    "as_iso": "PT0.00006S",
    "as_text": "60 microseconds"
  }
}
```

</details>

### Fixture setup and teardown

Pytest fixtures can be simple functions, or context managers that can clean up resources after a
test has finished. `pytest-scrutinize` records both the setup _and_ teardown times for all fixtures,
allowing you to precisely locate performance bottlenecks:

```python
@pytest.fixture
def slow_teardown():
    yield
    time.sleep(1)
```

<details>
<summary>Example</summary>

```json
{
  "meta": {
    "worker": "master",
    "recorded_at": "2024-08-17T21:23:54.736177Z",
    "thread_name": "MainThread"
  },
  "type": "fixture",
  "name": "pytest_django.plugin._django_set_urlconf",
  "short_name": "_django_set_urlconf",
  "test_id": "tests/test_plugin.py::test_all[normal]",
  "scope": "function",
  "setup": {
    "as_nanoseconds": 5792,
    "as_microseconds": 5,
    "as_iso": "PT0.000005S",
    "as_text": "5 microseconds"
  },
  "teardown": {
    "as_nanoseconds": 2167,
    "as_microseconds": 2,
    "as_iso": "PT0.000002S",
    "as_text": "2 microseconds"
  },
  "runtime": {
    "as_nanoseconds": 7959,
    "as_microseconds": 7,
    "as_iso": "PT0.000007S",
    "as_text": "7 microseconds"
  }
}
```

</details>

### Django SQL queries

Information on Django SQL queries can be captured with the `--scrutinize-django-sql` flag. By
default, the hash of the SQL query is captured (allowing you to count duplicate queries), but
the raw SQL can also be captured:

```shell
# Log the hashes of the executed SQL queries
pytest --scrutinize=tests.jsonl.gz --scrutinize-django-sql
# Log raw SQL queries. Warning: May produce very large files!
pytest --scrutinize=tests.jsonl.gz --scrutinize-django-sql=query
```

<details>
<summary>Example</summary>

```json
{
  "meta": {
    "worker": "master",
    "recorded_at": "2024-08-17T22:02:47.218492Z",
    "thread_name": "MainThread"
  },
  "name": "django_sql",
  "test_id": "test_django.py::test_case",
  "fixture_name": "test_django.teardown_fixture",
  "runtime": {
    "as_nanoseconds": 18375,
    "as_microseconds": 18,
    "as_iso": "PT0.000018S",
    "as_text": "18 microseconds"
  },
  "type": "django-sql",
  "sql_hash": "be0beb84a58eab3bdc1fc4214f90abe9e937e5cc7f54008e02ab81d51533bc16",
  "sql": "INSERT INTO \"django_app_dummymodel\" (\"foo\") VALUES (%s) RETURNING \"django_app_dummymodel\".\"id\""
}
```

</details>

### Record additional functions

Any arbitrary Python function can be captured by passing a comma-separated string of paths to
`--scrutinize-func`:

```shell
# Record all boto3 clients that are created, along with their timings:
pytest --scrutinize=tests.jsonl.gz --scrutinize-func=botocore.session.Session.create_client
```

<details>
<summary>Example</summary>

```json
{
  "meta": {
    "worker": "gw0",
    "recorded_at": "2024-08-17T22:02:44.296938Z",
    "thread_name": "MainThread"
  },
  "name": "urllib.parse.parse_qs",
  "test_id": "test_mock.py::test_case",
  "fixture_name": "test_mock.teardown_fixture",
  "runtime": {
    "as_nanoseconds": 2916,
    "as_microseconds": 2,
    "as_iso": "PT0.000002S",
    "as_text": "2 microseconds"
  },
  "type": "mock"
}
```

</details>

### Garbage collection

Garbage collection events can be captured with the `--scrutinize-gc` flag. Every GC is captured,
along with the total time and number of objects collected. This can be used to find tests that
generate significant GC pressure by creating lots of circular-referenced objects:

```shell
pytest --scrutinize=tests.jsonl.gz --scrutinize-gc
```

<details>
<summary>Example</summary>

```json
{
  "meta": {
    "worker": "gw0",
    "recorded_at": "2024-08-17T22:02:44.962665Z",
    "thread_name": "MainThread"
  },
  "type": "gc",
  "runtime": {
    "as_nanoseconds": 5404333,
    "as_microseconds": 5404,
    "as_iso": "PT0.005404S",
    "as_text": "5404 microseconds"
  },
  "collected_count": 279,
  "generation": 2
}
```

</details>