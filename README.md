# pytest-scrutinize

![PyPI - Python Version](https://img.shields.io/pypi/pyversions/pytest-scrutinize) ![PyPI - Status](https://img.shields.io/pypi/status/pytest-scrutinize) ![PyPI - Format](https://img.shields.io/pypi/format/pytest-scrutinize) ![PyPI - License](https://img.shields.io/pypi/l/pytest-scrutinize)

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

## Data captured:

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

### Django SQL queries

Information on Django SQL queries can be captured with the `--scrutinize-django-sql` flag. By 
default the hash of the SQL query is captured (allowing you to count duplicate queries), but 
the raw SQL can also be captured:

```shell
# Log the hashes of the executed SQL queries
pytest --scrutinize=tests.jsonl.gz --scrutinize-django-sql
# Log raw SQL queries. Warning: May produce very large files!
pytest --scrutinize=tests.jsonl.gz --scrutinize-django-sql=query
```

### Record additional functions 

Any arbitrary Python function can be captured by passing a comma-separated string of paths to 
`--scrutinize-func`:

```shell
# Record all boto3 clients that are created, along with their timings:
pytest --scrutinize=tests.jsonl.gz --scrutinize-func=botocore.session.Session.create_client
```

### Garbage collection

Garbage collection events can be captured with the `--scrutinize-gc` flag. Every GC is captured, 
along with the total time and number of objects collected. This can be used to find tests that 
generate significant GC pressure by creating lots of circular-referenced objects:

```shell
pytest --scrutinize=tests.jsonl.gz --scrutinize-gc
```
