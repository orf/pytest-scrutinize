import inspect


def is_generator_fixture(func):
    genfunc = inspect.isgeneratorfunction(func)
    return genfunc and not inspect.iscoroutinefunction(func)
