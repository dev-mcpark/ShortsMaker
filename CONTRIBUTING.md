# Contributing to ShortsMaker 🎬

First off, thank you for considering contributing to ShortsMaker! It's people like you that make ShortsMaker such a great tool.

## 🚀 Getting Started

1. **Fork the repository** on GitHub.
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/your-username/ShortsMaker.git
   cd ShortsMaker
   ```
3. **Set up the development environment**:
   We use `uv` for dependency management, but `pip` works too.
   ```bash
   pip install -e .
   ```
4. **Create a branch** for your feature or bugfix:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## 🛠️ Development Guidelines

- **Code Style**: We follow standard Python PEP 8 guidelines. Using `ruff` for linting is recommended.
- **Modularity**: When adding new features to the planner or generator, keep them modular (like `ContentExtractor` or `ContentAnalyzer`).
- **Testing**: If you add new logic, please provide a simple test script in the `tests/` directory.

## 📮 Submitting a Pull Request

1. Ensure your code passes basic linting.
2. Commit your changes with clear, descriptive messages.
3. Push to your fork and submit a Pull Request to the `main` branch of the original repository.
4. Describe your changes in detail in the PR description.

## ⚖️ License

By contributing, you agree that your contributions will be licensed under its MIT License.
