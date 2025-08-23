"""
Generate a .env file for the specified environment group in env.ini.

Usage:
python generate_env.py <environment>

Example:
python generate_env.py dev

Example env.ini:
APP_NAME=MyApp
LOG_LEVEL=INFO

[prod]
DB_HOST=prod.example.com
DB_USER=prod_user
DB_PASSWORD=secret

[test]
DB_HOST=localhost
DB_USER=test_user
DB_PASSWORD=test_pass
LOG_LEVEL=DEBUG

[staging|prod]
DB_HOST=staging.example.com

"""

import configparser
import sys
import re

def parse_ini(file_path):
    """ Parses the INI file and returns a dictionary of environments with inheritance resolved. """
    with open(file_path, "r") as f:
        lines = f.readlines()

    common_vars = {}
    ini_content = ""
    common_section_added = False

    # Process file lines to separate common variables from sections
    for line in lines:
        if re.match(r"^\[.*\]", line):  # If line starts with [section], it's an INI section
            common_section_added = True
        if not common_section_added and "=" in line:  # Common variables before first section
            key, value = line.strip().split("=", 1)
            common_vars[key] = value
        else:
            ini_content += line  # Keep section-based content for configparser

    # Read remaining INI content
    config = configparser.ConfigParser(allow_no_value=True, delimiters=('=',))
    config.optionxform = str  # Preserve case sensitivity
    config.read_string(ini_content)

    envs = {}

    # Process sections and handle inheritance
    for section in config.sections():
        if "|" in section:  # Handle inheritance
            child, parent = section.split("|", 1)
            envs[child] = {**envs.get(parent, {}), **dict(config[section])}  # Merge parent and child values
        else:
            envs[section] = dict(config[section])  # Standard section

    # Merge common variables into each environment
    for env in envs:
        envs[env] = {**common_vars, **envs[env]}  # Common variables apply to all

    return envs, common_vars

def generate_env_file(env_name=None, ini_file="env.ini", output_file=".env"):
    """ Generates a .env file for the specified environment group. """
    envs, common_vars = parse_ini(ini_file)

    if env_name is None:  # If no environment is specified, only output common variables
        env_data = common_vars
        env_data["ENV_NAME"] = None
        print("ℹ️  No environment specified. Generating .env with common variables only.")
    elif env_name not in envs:
        print(f"❌ Error: Environment '{env_name}' not found in {ini_file}")
        sys.exit(1)
    else:
        env_data = envs[env_name]
        env_data["ENV_NAME"] = env_name

    with open(output_file, "w") as f:
        for key, value in env_data.items():
            f.write(f"{key}={value}\n")

    print(f"✅ Generated '{output_file}' for {'common variables' if env_name is None else f'environment {env_name}'}")

if __name__ == "__main__":
    env_name = sys.argv[1] if len(sys.argv) > 1 else None
    generate_env_file(env_name)
