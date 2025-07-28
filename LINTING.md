# Guide des outils de linting

Ce projet utilise `uv` pour la gestion des dépendances et plusieurs outils de linting configurés pour assurer la qualité du code.

## Outils configurés

- **Ruff** : Linting rapide et formatting (remplace flake8, isort, etc.)
- **Pylint** : Analyse statique avancée
- **MyPy** : Vérification de types (configuration permissive)

## Installation des dépendances

```bash
# Installer uv (si pas déjà fait)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Installer les dépendances de développement
uv sync --dev
```

## Méthodes pour lancer le linting

### 1. Makefile (recommandé)

```bash
# Voir toutes les commandes disponibles
make help

# Lancer tous les outils de linting
make lint

# Lancer avec auto-fix
make lint-fix

# Formater le code uniquement
make format

# Vérifier le formatage sans changer
make check

# Outils individuels
make ruff
make pylint
make mypy
```

### 2. Script Python

```bash
# Tous les outils
python scripts/lint.py

# Avec auto-fix
python scripts/lint.py --fix

# Vérification formatage uniquement
python scripts/lint.py --check-only

# Outils spécifiques
python scripts/lint.py ruff
python scripts/lint.py ruff,pylint
python scripts/lint.py mypy
```

### 3. Script bash simple

```bash
# Lancer tous les outils
./lint.sh
```

### 4. Commandes uv directes

```bash
# Ruff
uv run ruff check fastapi_crudrouter
uv run ruff check --fix fastapi_crudrouter
uv run ruff format fastapi_crudrouter

# Pylint
uv run pylint fastapi_crudrouter

# MyPy
uv run mypy fastapi_crudrouter
```

## Configuration

Toute la configuration se trouve dans `pyproject.toml` :

- `[tool.ruff]` : Configuration ruff
- `[tool.pylint]` : Configuration pylint  
- `[tool.mypy]` : Configuration mypy

## Notes importantes

- **Ruff** est configuré pour corriger automatiquement de nombreux problèmes avec `--fix`
- **Pylint** donne une note sur 10 (objectif : >9.0)
- **MyPy** est configuré en mode permissif pour éviter les conflits de types complexes avec SQLAlchemy

## Workflow de développement recommandé

1. Développer votre code
2. Lancer `make lint-fix` pour corriger automatiquement
3. Corriger manuellement les problèmes restants
4. Commit

## Scripts disponibles

- `scripts/lint.py` : Script Python complet avec options
- `lint.sh` : Script bash simple
- `Makefile` : Cibles make pour tous les cas d'usage

## Exclusions

Les erreurs de tests sont largement ignorées car ils ne font plus partie du périmètre après la refactorisation (SQLAlchemy async uniquement).