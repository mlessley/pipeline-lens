class FakeSession:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self._results: dict[str, list] = {}

    def set_result(self, statement: str, records: list) -> None:
        self._results[statement] = records

    def run(self, statement: str, **params):
        self.calls.append((statement, params))
        return self._results.get(statement, [])

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeDriver:
    def __init__(self):
        self.fake_session = FakeSession()

    def session(self):
        return self.fake_session


class FakeNode:
    def __init__(self, element_id: str, labels: list[str], properties: dict):
        self.element_id = element_id
        self.labels = labels
        self._properties = properties

    def items(self):
        return self._properties.items()

    def keys(self):
        return self._properties.keys()

    def __getitem__(self, key):
        return self._properties[key]
