# Contributing to Celia Clips

Thanks for your interest in contributing to Celia Clips — part of the **Celia** suite by [Inminente](https://inminente.co).

## Getting Started

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/celia-clips.git
   cd celia-clips
   ```
3. Create a virtual environment and install in dev mode:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -e ".[dev]"
   ```

## Development

### Code Style

We use [Ruff](https://github.com/astral-sh/ruff) for linting and formatting:

```bash
ruff check packages/ server/
ruff format packages/ server/
```

### Running Tests

```bash
pytest tests/
```

### Branch Naming

- `feature/description` — new features
- `fix/description` — bug fixes
- `docs/description` — documentation changes

## Pull Request Guidelines

1. Create a feature branch from `main`
2. Write clear commit messages
3. Add tests for new functionality
4. Ensure all tests pass
5. Update documentation if needed
6. Submit a PR using the template provided

## Reporting Issues

Use the GitHub issue templates for:
- 🐛 **Bug reports**: Include steps to reproduce, expected vs actual behavior
- ✨ **Feature requests**: Describe the use case and proposed solution

## Code of Conduct

Please read our [Code of Conduct](CODE_OF_CONDUCT.md) before contributing.
