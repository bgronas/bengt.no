"""YAML loading with YAML 1.2 style scalars.

PyYAML follows YAML 1.1, where the bare word `no` is the boolean false. This
site has a language whose key is `no`, and Hugo and Pages CMS both read `no` as
a string. The loader here matches them: only true/false are booleans, and
timestamps stay the strings the author wrote.
"""

from __future__ import annotations

import re
from typing import Any

import yaml


class Loader(yaml.SafeLoader):
    pass


_DROP = ("tag:yaml.org,2002:timestamp", "tag:yaml.org,2002:bool")
Loader.yaml_implicit_resolvers = {
    key: [(tag, regexp) for tag, regexp in resolvers if tag not in _DROP]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
Loader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


def load(text: str) -> Any:
    return yaml.load(text, Loader=Loader)  # noqa: S506 - SafeLoader subclass
