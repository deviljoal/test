# -*- coding: utf-8 -*-

# Importation des modules nécessaires
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import string
import subprocess
import sys
import tarfile
import time
import traceback
from datetime import datetime
from distutils.dir_util import copy_tree
from pathlib import Path
from typing import Dict, List, Tuple, Optional, NoReturn, Union, Callable, Any

# Fichier de configuration du DSL
dsl_log_file = "dsl.log4j.xml"

# Fonction pour adapter les arguments de commande lors de l'utilisation de Bash sur Windows
def adapt_the_command_arguments_when_using_bash_on_windows(command_arguments):
    command_arguments_to_use = command_arguments[:]
    if platform.system() == "Windows":
        command_arguments_to_use = ["bash.exe", "-c", " ".join(command_arguments)]
    return command_arguments_to_use

# Fonction pour exécuter un sous-processus
def run_subprocess(log_file_path: Path,
                   arguments: Union[list, str],
                   *subprocess_args,
                   environment_variables: dict = None,
                   current_working_directory: Path = None,
                   **subprocess_kwargs) -> subprocess.Popen:
    # Ouverture du processus en tant que sous-processus avec les arguments donnés
    with subprocess.Popen(arguments, *subprocess_args,
                          env=environment_variables,
                          cwd=current_working_directory,
                          text=True,
                          stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT,
                          bufsize=1,
                          **subprocess_kwargs) as running_process, log_file_path.open("w") as log_file:
        # Lecture de la sortie du processus ligne par ligne
        for line in running_process.stdout:
            # Ajout d'un horodatage et écriture de la ligne dans le fichier de journal
            line = datetime.now().strftime("%H:%M:%S.%f")[:-3] + "- " + line
            print(line[:-1])
            log_file.write(line)
            log_file.flush()
    return running_process

# Fonction pour exécuter un sous-processus en détaché
def run_detach_subprocess(log_file_path: Path,
                          arguments: list,
                          environment_variables: dict = None,
                          current_working_directory: Path = None) -> subprocess.Popen:
    # Fonction interne pour normaliser les chemins de fichier
    def norm_path(file_path: Path) -> str:
        return str(file_path).replace('\\', '/')

    # Construction de la commande Python pour lancer le sous-processus
    python_command_string = f"""
import subprocess
import platform
from datetime import datetime
def launch_subprocess(args_to_use, env_to_use, cwd_to_use, log_file_to_use):
    if platform.system() == "Windows":
        creation_flags = subprocess.CREATE_NO_WINDOW
    else:
        creation_flags = 0
    with subprocess.Popen(args_to_use, env=env_to_use, cwd=cwd_to_use, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, creationflags=creation_flags) as running_process, open(log_file_to_use, "w") as log_file:
        for line in running_process.stdout:
            line = datetime.now().strftime("%H:%M:%S.%f")[:-3] + "- " + line
            print(line[:-1])
            log_file.write(line)
            log_file.flush()
launch_subprocess({arguments}, {environment_variables}, "{norm_path(current_working_directory)}", "{norm_path(log_file_path)}")
            """

    python_command_arguments = ["python", "-c", python_command_string]

    # Exécution du processus détaché en fonction de la plateforme
    if platform.system() == "Windows":
        process = subprocess.Popen(python_command_arguments, cwd=current_working_directory.parent, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        process = subprocess.Popen(python_command_arguments, cwd=current_working_directory.parent, start_new_session=True)

    return process

# Classe représentant un chemin dans un dictionnaire
class DictPath:

    # Méthode de classe pour vérifier si une étape de chemin est un index
    @classmethod
    def is_a_path_step_as_index(cls, path_step):
        if isinstance(path_step, int) and path_step >= 0:
            return True
        return False

    # Méthode de classe pour vérifier si une étape de chemin est une clé
    @classmethod
    def is_a_path_step_as_key(cls, path_step):
        if isinstance(path_step, str):
            return True
        return False

    # Initialisation de l'objet DictPath
    def __init__(self, from_dict_path: DictPath = None, from_dict_path_as_list: Optional[List[str]] = None):
        if from_dict_path_as_list is not None:
            self.dictPath = from_dict_path_as_list[:]
        elif from_dict_path is None:
            self.dictPath = []
        else:
            self.dictPath = from_dict_path.get_dict_path_as_list()

    # Représentation sous forme de chaîne de caractères de l'objet DictPath
    def __str__(self):
        return "->".join([str(x) for x in self.dictPath])

    # Méthode pour obtenir le chemin sous forme de liste
    def get_dict_path_as_list(self):
        return self.dictPath[:]

    # Méthode pour vérifier si le chemin est vide
    def is_empty(self):
        return len(self.dictPath) == 0

    # Méthode pour ajouter une étape au chemin
    def add_a_step_to_the_path(self, path_step):
        if not self.is_a_path_step_as_key(path_step) and not self.is_a_path_step_as_index(path_step):
            raise UserWarning(f"Unexpected path step type (expected string or positive int)")
        self.dictPath = [path_step] + self.dictPath

    # Méthode pour obtenir la dernière étape du chemin
    def get_the_last_step_of_the_path(self):
        if self.is_empty():
            return None
        return self.dictPath[0]

    # Méthode pour obtenir et supprimer la dernière étape du chemin
    def get_and_remove_the_last_step_of_the_path(self):
        if self.is_empty():
            return None
        last_step = self.dictPath[0]
        del self.dictPath[0]
        return last_step

    # Méthode pour obtenir une sous-chaîne du chemin
    def get_subpath_as_dict_path(self):
        return DictPath(from_dict_path_as_list=self.dictPath[1:])

# Classe pour manipuler un dictionnaire basé sur un chemin
class PathBasedDictionary:

    # Initialisation de l'objet PathBasedDictionary
    def __init__(self, dictionary_to_use: Optional[dict] = None):
        if dictionary_to_use is None:
            self.pathBasedDictionary = {}
        else:
            self.pathBasedDictionary = dictionary_to_use

    # Méthode pour obtenir la valeur d'un chemin dans le dictionnaire
    def get_the_value_of_a_path(self, path_to_use: DictPath) -> Any:
        path = path_to_use.get_dict_path_as_list()
        current_dict = self.pathBasedDictionary
        while len(path) > 0:
            current_step = path.pop()
            if DictPath.is_a_path_step_as_index(current_step):
                current_dict = current_dict[int(current_step)]
            elif DictPath.is_a_path_step_as_key(current_step):
                current_dict = current_dict[current_step]
            else:
                raise UserWarning(f"Unexpected path step type (expected string or positive int)")
        return current_dict

    # Méthode pour définir la valeur d'un chemin dans le dictionnaire
    def set_the_value_of_a_path(self, path_to_use: DictPath, value_to_set: Any) -> NoReturn:
        path = path_to_use.get_dict_path_as_list()
        current_dict = self.pathBasedDictionary
        while len(path) > 1:
            current_step = path.pop()
            if DictPath.is_a_path_step_as_index(current_step):
                current_dict = current_dict[int(current_step)]
            elif DictPath.is_a_path_step_as_key(current_step):
                current_dict = current_dict[current_step]
            else:
                raise UserWarning(f"Unexpected path step type (expected string or positive int)")
        last_step = path.pop()
        if DictPath.is_a_path_step_as_index(last_step):
            current_dict[int(last_step)] = value_to_set
        elif DictPath.is_a_path_step_as_key(last_step):
            current_dict[last_step] = value_to_set
        else:
            raise UserWarning(f"Unexpected path step type (expected string or positive int)")

# Classe utilitaire pour analyser les dictionnaires avec des fonctions de rappel pour traiter les clés et les valeurs
class DictionaryParser:

    # Initialisation de l'objet DictionaryParser
    def __init__(self,
                 dictionary_to_parse: dict,
                 on_key_encounter: Callable[[str, List[DictPath]], Union[str, None]],
                 on_value_encounter: Callable[[Any, List[DictPath]], Union[Any, None]],
                 dictionary_to_use: Optional[Dict[str, Any]] = None):
        self.dictionaryParser = dictionary_to_use
        self.parse_dictionary(dictionary_to_parse, on_key_encounter, on_value_encounter)

    # Méthode pour analyser le dictionnaire
    def parse_dictionary(self,
                         dictionary_to_parse: dict,
                         on_key_encounter: Callable[[str, List[DictPath]], Union[str, None]],
                         on_value_encounter: Callable[[Any, List[DictPath]], Union[Any, None]],
                         current_path: List[DictPath] = None) -> NoReturn:
        if current_path is None:
            current_path = []
        for key, value in dictionary_to_parse.items():
            # Création d'un nouveau chemin pour cette étape de clé
            current_path.append(DictPath(from_dict_path=current_path[-1] if len(current_path) > 0 else None))
            # Application de la fonction de rappel pour la clé
            key_to_use = on_key_encounter(key, current_path)
            if key_to_use is None:
                key_to_use = key
            # Application de la fonction de rappel pour la valeur
            value_to_use = on_value_encounter(value, current_path)
            if value_to_use is None:
                value_to_use = value
            # Traitement récursif si la valeur est un dictionnaire
            if isinstance(value_to_use, dict):
                self.parse_dictionary(value_to_use, on_key_encounter, on_value_encounter, current_path)
            # Retrait du chemin ajouté pour cette étape de clé
            current_path.pop()

# Classe pour analyser la description du déploiement
class DeploymentDescriptionParser:

    # Initialisation de l'objet DeploymentDescriptionParser
    def __init__(self,
                 deployment_description_to_parse: dict,
                 dictionary_to_use: Optional[Dict[str, Any]] = None):
        self.deploymentDescriptionParser = dictionary_to_use
        self.parse_deployment_description(deployment_description_to_parse)

    # Méthode pour analyser la description du déploiement
    def parse_deployment_description(self,
                                     deployment_description_to_parse: dict,
                                     current_path: List[DictPath] = None) -> NoReturn:
        if current_path is None:
            current_path = []
        # Définition des fonctions de rappel pour la clé et la valeur
        def on_key_encounter(key: str, path: List[DictPath]) -> str:
            return key

        def on_value_encounter(value: Any, path: List[DictPath]) -> Any:
            if isinstance(value, str):
                # Nettoyage des chaînes de caractères pour supprimer les espaces inutiles
                return value.strip()
            return value
        # Utilisation du DictionaryParser pour analyser la description du déploiement
        DictionaryParser(deployment_description_to_parse,
                         on_key_encounter,
                         on_value_encounter,
                         dictionary_to_use=self.deploymentDescriptionParser)

# Classe pour nettoyer la description du déploiement
class DeploymentDescriptionCleaner:

    # Initialisation de l'objet DeploymentDescriptionCleaner
    def __init__(self,
                 deployment_description_to_clean: dict,
                 dictionary_to_use: Optional[Dict[str, Any]] = None):
        self.deploymentDescriptionCleaner = dictionary_to_use
        self.clean_deployment_description(deployment_description_to_clean)

    # Méthode pour nettoyer la description du déploiement
    def clean_deployment_description(self,
                                     deployment_description_to_clean: dict,
                                     current_path: List[DictPath] = None) -> NoReturn:
        if current_path is None:
            current_path = []
        # Définition des fonctions de rappel pour la clé et la valeur
        def on_key_encounter(key: str, path: List[DictPath]) -> Union[str, None]:
            if key == "logging":
                # Ignorer la section de configuration du journal
                return None
            return key

        def on_value_encounter(value: Any, path: List[DictPath]) -> Union[Any, None]:
            if isinstance(value, dict):
                # Nettoyer les dictionnaires imbriqués
                return self.clean_deployment_description_recursively(value, path)
            return value
        # Utilisation du DictionaryParser pour nettoyer la description du déploiement
        DictionaryParser(deployment_description_to_clean,
                         on_key_encounter,
                         on_value_encounter,
                         dictionary_to_use=self.deploymentDescriptionCleaner)

    # Méthode récursive pour nettoyer les dictionnaires imbriqués dans la description du déploiement
    def clean_deployment_description_recursively(self,
                                                 deployment_description_to_clean: dict,
                                                 current_path: List[DictPath]) -> dict:
        cleaned_description = {}
        for key, value in deployment_description_to_clean.items():
            current_path.append(DictPath(from_dict_path=current_path[-1] if len(current_path) > 0 else None))
            # Ignorer les sections de configuration du journal
            if key != "logging":
                if isinstance(value, dict):
                    cleaned_description[key] = self.clean_deployment_description_recursively(value, current_path)
                else:
                    cleaned_description[key] = value
            current_path.pop()
        return cleaned_description

# Fonction pour extraire un fichier d'archive tar.gz
def extract_a_tar_gz_archive(archive_path: Path, extraction_directory: Path):
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(path=extraction_directory)

# Fonction pour valider un chemin de fichier
def validate_a_file_path(file_path: str) -> str:
    if os.path.isfile(file_path):
        return file_path
    raise FileNotFoundError(f"File not found at {file_path}")

# Fonction pour valider un chemin de répertoire
def validate_a_directory_path(directory_path: str) -> str:
    if os.path.isdir(directory_path):
        return directory_path
    raise NotADirectoryError(f"Directory not found at {directory_path}")

# Fonction pour valider un chemin de répertoire et le créer s'il n'existe pas
def validate_and_create_a_directory_path(directory_path: str) -> str:
    if not os.path.exists(directory_path):
        os.makedirs(directory_path)
    return directory_path

# Fonction pour valider un chemin de fichier et le créer s'il n'existe pas
def validate_and_create_a_file_path(file_path: str) -> str:
    if not os.path.exists(os.path.dirname(file_path)):
        os.makedirs(os.path.dirname(file_path))
    return file_path

# Fonction pour valider et obtenir le chemin complet d'un fichier
def validate_and_get_the_absolute_path(file_path: str) -> str:
    return os.path.abspath(file_path)

# Fonction pour calculer le hachage MD5 d'un fichier
def compute_the_md5_hash_of_a_file(file_path: str) -> str:
    md5_hash = hashlib.md5()
    with open(file_path, "rb") as file_to_hash:
        # Lecture du fichier en petits morceaux pour éviter la surcharge mémoire
        for chunk in iter(lambda: file_to_hash.read(4096), b""):
            md5_hash.update(chunk)
    return md5_hash.hexdigest()

# Fonction pour écrire un dictionnaire dans un fichier JSON
def write_a_dictionary_to_a_json_file(dictionary_to_write: dict, file_path: str):
    with open(file_path, "w") as json_file:
        json.dump(dictionary_to_write, json_file, indent=4)

# Fonction pour lire un fichier JSON dans un dictionnaire
def read_a_json_file_into_a_dictionary(file_path: str) -> dict:
    with open(file_path, "r") as json_file:
        return json.load(json_file)

# Fonction pour copier un fichier
def copy_a_file(source_file_path: str, destination_file_path: str):
    shutil.copyfile(source_file_path, destination_file_path)

# Fonction pour copier un répertoire
def copy_a_directory(source_directory_path: str, destination_directory_path: str):
    copy_tree(source_directory_path, destination_directory_path)

# Fonction pour vérifier si une chaîne de caractères est un numéro de version
def is_a_version_string(version_string: str) -> bool:
    return bool(re.match(r'^(\d+)\.(\d+)\.(\d+)$', version_string))

# Fonction pour vérifier si une chaîne de caractères est un numéro de version
def is_a_valid_version(version_string: str) -> bool:
    return bool(re.match(r'^(\d+)\.(\d+)\.(\d+)$', version_string))

# Fonction pour vérifier si un chemin de fichier est un fichier DSL
def is_a_dsl_file(file_path: str) -> bool:
    return file_path.endswith('.dsl')

# Fonction pour interrompre proprement l'exécution
def graceful_exit(signal_received: int, frame: Any):
    print("Exiting gracefully...")
    sys.exit(0)

# Installation de la gestion de signal pour une sortie propre
signal.signal(signal.SIGINT, graceful_exit)
signal.signal(signal.SIGTERM, graceful_exit)

