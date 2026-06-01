"""
Main class for managing the configuration files
Steps to use it:
    1. Create a file with the configuration data in JSON format.
    2. Create an instance of Config with the path to the file.
    3. Use the attributes of the instance to access the data. If the attribute does not exist, returns None.
    4. Use the data as needed.
    5. Profit.
Example:
    config = Config('config.json')
    print(config.api_key)
    print(config.api_secret)
    print(config.api_url)
    print(config.api_version)
    print(config.non_existent_attribute)  # Returns None

"""

import json, os
from dotenv import load_dotenv


class Config:
    def __init__(self, filepath):
        self._data = {}
        try:
            with open(filepath, 'r') as file:
                self._data = json.load(file)
        except FileNotFoundError:
            print(f"El archivo {filepath} no fue encontrado.")
        except json.JSONDecodeError as e:
            print(f"Error al decodificar JSON en el archivo {filepath}. Error: {str(e)}")

    def __getattr__(self, name):
        # Este método se llama si no se encuentra el atributo de manera regular.
        # Buscamos el nombre del atributo en los datos cargados.
        # Si el atributo no existe, se devuelve None.
        v = self._data.get(name, None)
        return v if not v.isnumeric() else int(v)

    def __str__(self):
        return str(self._data)

    def __repr__(self):
        return self.__str__()


#CONFIG = Config('config.json')
# NEW SUPPORT FOR ENVIRONMENT VARIABLES
load_dotenv()

class EnvConfig:
    def __init__(self):
        pass

    def __getattr__(self, item):
        v = os.getenv(item, None)
        return None if not v else v if not v.isnumeric() else int(v)


CONFIG = EnvConfig()
