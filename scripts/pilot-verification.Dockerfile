FROM python:3.12-slim
RUN python -m pip install --no-cache-dir \
    'pydantic>=2.7,<3' 'PyYAML>=6.0.1,<7' 'pandas>=2.2,<3' \
    'numpy>=1.26,<2.4' 'pyarrow>=18,<24' 'pytest>=8,<10' 'ruff>=0.9,<1'
