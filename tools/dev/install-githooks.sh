#!/bin/bash
pip3 install flake8==3.7.8
cp -rf tools/dev/git-hooks/pre-commit .git/hooks
