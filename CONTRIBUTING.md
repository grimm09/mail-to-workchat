# Contributing

[English](CONTRIBUTING.md) | [简体中文](CONTRIBUTING.zh-CN.md)

1. Create a focused branch.
2. Use only synthetic mail fixtures and placeholder domains such as `example.com`.
3. Run `python -m compileall -q src` and the full unit-test suite.
4. Run the repository privacy scan before opening a pull request.
5. Explain behavior and security changes in the pull request description.
6. Update both language versions when changing behavior, examples, privacy boundaries or validation claims.
   Keep executable commands and configuration keys unchanged when translating prose. See [language support](docs/languages.md).

Never contribute mailbox exports, runtime databases, logs, webhook URLs, passwords,
customer identifiers, or production reply templates.
