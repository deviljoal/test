# -*- coding: utf-8 -*-

# Importation des modules et des fonctions nécessaires
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

# Définition du nom du fichier de journalisation DSL
dsl_log_file = "dsl.log4j.xml"

# Fonction pour adapter les arguments de la commande lors de l'utilisation de Bash sur Windows
def adapt_the_command_arguments_when_using_bash_on_windows(command_arguments):
    command_arguments_to_use = command_arguments[:]
    if platform.system() == "Windows":
        command_arguments_to_use = ["bash.exe", "-c", " ".join(command_arguments)]
    return command_arguments_to_use

# Fonction pour exécuter un processus subprocess et journaliser la sortie
def run_subprocess(log_file_path: Path,
                   arguments: Union[list, str],
                   *subprocess_args,
                   environment_variables: dict = None,
                   current_working_directory: Path = None,
                   **subprocess_kwargs) -> subprocess.Popen:
    # Ouverture du processus subprocess et du fichier journal
    with subprocess.Popen(arguments, *subprocess_args,
                          env=environment_variables,
                          cwd=current_working_directory,
                          text=True,
                          stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT,
                          bufsize=1,
                          **subprocess_kwargs) as running_process, log_file_path.open("w") as log_file:
        # Lecture de la sortie du processus subprocess et journalisation
        for line in running_process.stdout:
            line = datetime.now().strftime("%H:%M:%S.%f")[:-3] + "- " + line
            print(line[:-1])
            log_file.write(line)
            log_file.flush()
    return running_process

# Fonction pour exécuter un processus subprocess détaché et journaliser la sortie
def run_detach_subprocess(log_file_path: Path,
                          arguments: list,
                          environment_variables: dict = None,
                          current_working_directory: Path = None) -> subprocess.Popen:
    # Fonction interne pour normaliser les chemins
    def norm_path(file_path: Path) -> str:
        return str(file_path).replace('\\', '/')

    # Création de la chaîne de commande Python pour le processus subprocess détaché
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

    # Exécution du processus subprocess détaché
    if platform.system() == "Windows":
        process = subprocess.Popen(python_command_arguments, cwd=current_working_directory.parent, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        process = subprocess.Popen(python_command_arguments, cwd=current_working_directory.parent, start_new_session=True)    # Try adding this in case of terminal problems: , stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    return process

# Classe représentant un chemin dans un dictionnaire
class DictPath:
    # Méthode de classe pour vérifier si une étape du chemin est un index
    @classmethod
    def is_a_path_step_as_index(cls, path_step):
        if isinstance(path_step, int) and path_step >= 0:
            return True
        return False

    # Méthode de classe pour vérifier si une étape du chemin est une clé
    @classmethod
    def is_a_path_step_as_key(cls, path_step):
        if isinstance(path_step, str):
            return True
        return False

    # Méthode d'initialisation de la classe DictPath
    def __init__(self, from_dict_path: DictPath = None, from_dict_path_as_list: Optional[List[str]] = None):
        if from_dict_path_as_list is not None:
            self.dictPath = from_dict_path_as_list[:]
        elif from_dict_path is None:
            self.dictPath = []
        else:
            self.dictPath = from_dict_path.get_dict_path_as_list()

    # Méthode spéciale pour convertir l'objet en chaîne
    def __str__(self):
        return "->".join([str(x) for x in self.dictPath])

    # Méthode pour obtenir le chemin du dictionnaire sous forme de liste
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

    # Méthode pour obtenir le chemin vers le parent
    def get_the_path_to_parent(self):
        if self.is_empty():
            return None
        return DictPath(from_dict_path_as_list=self.dictPath[1:])

    # Méthode pour obtenir le chemin vers une étape suivante
    def get_the_path_to_a_following_step(self, following_path_step: Union[str, int]) -> NoReturn:
        new_dict_path = DictPath(from_dict_path=self)
        new_dict_path.add_a_step_to_the_path(following_path_step)
        return new_dict_path

    # Méthode pour supprimer la dernière étape du chemin
    def pop_the_last_step_of_the_path(self):
        return self.dictPath.pop(0)

    # Méthode pour supprimer la première étape du chemin
    def pop_the_first_step_of_the_path(self):
        return self.dictPath.pop()

# Classe pour manipuler un dictionnaire basé sur un chemin
class PathBasedDictionary:
    # Méthode d'initialisation de la classe PathBasedDictionary
    def __init__(self, root_dict: dict):
        self.root_dict = root_dict

    # Méthode pour obtenir la valeur pointée par un chemin dans le dictionnaire
    def get_the_value_pointed_by_a_dict_path(self, dict_path: DictPath, default_value: Any = "--raise--") -> Any:
        if dict_path.is_empty():
            return self.root_dict

        working_dict_path = DictPath(from_dict_path=dict_path)
        working_value = self.root_dict
        while not working_dict_path.is_empty():
            key_or_index = working_dict_path.pop_the_first_step_of_the_path()

            if isinstance(working_value, dict):
                if not DictPath.is_a_path_step_as_key(key_or_index):
                    raise UserWarning(f"The path '{working_dict_path}' is not a key in the parent dict")
                working_value = working_value.get(key_or_index, None)
                if working_value is None:
                    if default_value == "--raise--":
                        raise UserWarning(f"The value associated to the path '{working_dict_path}' is not found")
                    else:
                        working_value = default_value
            elif isinstance(working_value, list):
                if not DictPath.is_a_path_step_as_index(key_or_index):
                    raise UserWarning(f"The path '{working_dict_path}' is not an index in the parent list")
                try:
                    working_value = working_value[key_or_index]
                except IndexError:
                    raise UserWarning(f"The value associated to the path '{working_dict_path}' is not found")

        return working_value

    # Méthode pour définir la valeur pointée par un chemin dans le dictionnaire
    def set_the_value_pointed_by_a_dict_path(self, value: Any, dict_path: DictPath) -> NoReturn:
        if dict_path.is_empty():
            return self.root_dict

        key_or_index = dict_path.get_the_last_step_of_the_path()
        key_parent = dict_path.get_the_path_to_parent()
        parent_dict_or_list = self.get_the_value_pointed_by_a_dict_path(key_parent)
        try:
            parent_dict_or_list[key_or_index] = value
        except (TypeError, IndexError, KeyError) as e:
            raise UserWarning(f"Set the value associated to the path '{dict_path}' failed: {e}")
# Définition de la fonction pour remplacer la dernière clé donnée par un chemin dans un dictionnaire
def replace_the_last_key_given_by_a_dict_path(self, dict_path: DictPath, new_last_key: str, new_pointed_value: Optional[Any] = None) -> NoReturn:
    # Récupération de la dernière clé du chemin
    key = dict_path.get_the_last_step_of_the_path()
    # Vérification si la dernière étape du chemin est une clé
    if not DictPath.is_a_path_step_as_key(key):
        raise UserWarning(f"The path '{dict_path}' last step is not a key")
    # Récupération du parent du dernier élément du chemin
    parent_dict = self.get_the_value_pointed_by_a_dict_path(dict_path.get_the_path_to_parent())
    # Vérification si le parent est un dictionnaire
    if not isinstance(parent_dict, dict):
        raise UserWarning(f"The path '{dict_path}' last step parent is not a dict")

    # Sélection de la valeur à utiliser pour la nouvelle clé
    if new_pointed_value is not None:
        value = new_pointed_value
    else:
        value = self.get_the_value_pointed_by_a_dict_path(dict_path)

    # Récupération de la position de la clé dans le dictionnaire parent
    key_position = list(parent_dict.keys()).index(key)
    # Création d'une liste d'items parent en insérant la nouvelle clé à la position appropriée
    parent_items = list(parent_dict.items())
    parent_items.insert(key_position, (new_last_key, value))
    # Création d'un nouveau dictionnaire parent en supprimant l'ancienne clé et en mettant à jour avec la nouvelle liste d'items
    new_parent_dict = dict(parent_items)
    new_parent_dict.pop(key, None)

    # Effacement et mise à jour du dictionnaire parent
    parent_dict.clear()
    parent_dict.update(new_parent_dict)

# Définition de la fonction pour supprimer la dernière clé donnée par un chemin dans un dictionnaire
def delete_the_last_key_given_by_a_dict_path(self, dict_path: DictPath) -> NoReturn:
    # Récupération de la dernière clé du chemin
    key = dict_path.get_the_last_step_of_the_path()
    # Vérification si la dernière étape du chemin est une clé
    if not DictPath.is_a_path_step_as_key(key):
        raise UserWarning(f"The path '{dict_path}' last step is not a key")
    # Récupération du parent du dernier élément du chemin
    parent_dict = self.get_the_value_pointed_by_a_dict_path(dict_path.get_the_path_to_parent())
    # Vérification si le parent est un dictionnaire
    if not isinstance(parent_dict, dict):
        raise UserWarning(f"The path '{dict_path}' last step parent is not a dict")

    # Suppression de la clé du dictionnaire parent
    parent_dict.pop(key, None)

# Classe pour analyser un dictionnaire
class DictionaryParser:
    # Constantes pour les actions sur les clés
    IGNORE_THE_KEY = "--ignore-the-key--"
    DELETE_THE_KEY = "--delete-the-key--"

    def __init__(self, callback_on_key_analysis_starting: Callable[[str, DictPath, PathBasedDictionary], Optional[str]],
                 callback_on_key_analysis_ending: Callable[[str, DictPath, PathBasedDictionary], NoReturn],
                 callback_on_the_value_at_the_end_of_an_analyzed_path: Callable[[DictPath, PathBasedDictionary], bool]):

        self.callback_on_key_analysis_starting = callback_on_key_analysis_starting
        self.callback_on_key_analysis_ending = callback_on_key_analysis_ending
        self.callback_on_the_value_at_the_end_of_an_analyzed_ = callback_on_the_value_at_the_end_of_an_analyzed_path

    # Méthode pour analyser un dictionnaire
    def parse_dict(self, dict_to_parse: dict):
        self._parse_path_base_dict(PathBasedDictionary(dict_to_parse))

    # Méthode interne pour analyser un dictionnaire basé sur un chemin
    def _parse_path_base_dict(self, path_base_dict: PathBasedDictionary, dict_path: DictPath = None) -> NoReturn:
        if dict_path is None:
            dict_path = DictPath()

        dict_path_value = path_base_dict.get_the_value_pointed_by_a_dict_path(dict_path)

        if isinstance(dict_path_value, list):
            for index, value in enumerate(dict_path_value):
                new_dict_path = dict_path.get_the_path_to_a_following_step(index)
                self._parse_path_base_dict(path_base_dict, new_dict_path)
        elif isinstance(dict_path_value, dict):
            analysed_dict_keys = list(dict_path_value.keys())
            for key in analysed_dict_keys:
                new_key = self.callback_on_key_analysis_starting(key, dict_path, path_base_dict)
                if new_key == self.IGNORE_THE_KEY:
                    continue
                if new_key == self.DELETE_THE_KEY:
                    path_base_dict.delete_the_last_key_given_by_a_dict_path(dict_path.get_the_path_to_a_following_step(key))
                    continue
                new_dict_path = dict_path.get_the_path_to_a_following_step(new_key)
                self._parse_path_base_dict(path_base_dict, new_dict_path)
                self.callback_on_key_analysis_ending(new_key, dict_path, path_base_dict)
        else:
            if self.callback_on_the_value_at_the_end_of_an_analyzed_(dict_path, path_base_dict):
                self._parse_path_base_dict(path_base_dict, dict_path)

# Classe pour analyser une description de déploiement
class DeploymentDescriptionParser:

    key_words = {
        "label_of_the_deployment_target": "--deployment-target--",
        "label_of_is_present_test": "--isPresent--",
        "label_of_the_gan_project_name": "--ganProjectName--",
        "label_of_the_gan_version": "--ganVersion--",
        "label_of_a_node_dictionary": "--nodesByName--",
        "label_of_the_node_name": "--nodeName--",
        "label_of_a_components_group": "--componentsGroup--",
        "label_of_the_components_group_name": "--groupName--",
        "label_of_a_component_dictionary": "--componentsByDescriptionName--",
        "label_of_the_component_description_name": "--componentDescriptionName--",
        "label_of_the_component_name": "--componentName--",
        "label_of_a_component_env_var_dictionary": "--componentEnvironmentVariablesByName--",
        "label_of_a_database_dictionary": "--database--",
        "label_of_the_database_host": "--databaseHost--",
        "label_of_the_database_port": "--databasePort--",
        "label_of_a_template_definition": "--template--",
        "label_of_a_template_use": "--fromTemplate--",
        "label_of_an_just_to_differentiate_at_building_time": "--justToDifferentiateAtBuildingTime--",
        "label_of_a_pel_section": "--pel--",
        "label_of_a_pil_section": "--pil--",
        "label_of_a_jaeger_section": "--jaeger--",
    }

    def __init__(self):
        self._dictionaryParser = DictionaryParser(self._process_key_starting, self._process_key_ending, self._process_final_value)

    # Méthode pour vérifier si un mot-clé appartient à la classe DeploymentDescriptionParser
    def is_a_deployment_description_parser_key_word(self, key: str) -> bool:
        key_words_in_key = [key_word in key for key_word in self.key_words.values()]
        return True in key_words_in_key

    # Méthode pour vérifier si un nom de noeud ou de composant est correct
    def is_a_correct_node_or_component_name(self, key: str) -> bool:
        not_allowed_key_words = list(self.key_words.values())[:]
        not_allowed_key_words.remove(self.key_words["label_of_is_present_test"])
        not_allowed_key_words.remove(self.key_words["label_of_a_template_definition"])
        not_allowed_key_words.remove(self.key_words["label_of_a_template_use"])
        not_allowed_key_words.remove(self.key_words["label_of_an_just_to_differentiate_at_building_time"])

        key_words_in_key = [key_word in key for key_word in not_allowed_key_words]
        return not (True in key_words_in_key)

    # Méthode pour analyser un dictionnaire de description de déploiement
    def parse_deployment_description_dict(self, deployment_dict: dict) -> NoReturn:
        self._dictionaryParser.parse_dict(deployment_dict)

    # Méthode interne pour gérer le début d'une clé
    def _process_key_starting(self, new_key_in_the_path: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> Optional[str]:
        raise UserWarning(f"'_process_key_starting' function must be overridden")

    # Méthode interne pour gérer la fin d'une clé
    def _process_key_ending(self, new_key_in_the_path: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        raise UserWarning(f"'_process_key_ending' function must be overridden")

    # Méthode interne pour gérer la valeur finale
    def _process_final_value(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> bool:
        raise UserWarning(f"'_process_final_value' function must be overridden")

    # Méthode interne pour mettre à jour récursivement un dictionnaire
    def _deep_update(self, original_dict: dict, update_dict: dict) -> dict:
        for key, value in update_dict.items():
            if isinstance(value, dict):
                original_dict[key] = self._deep_update(original_dict.setdefault(key, {}), value)
            else:
                original_dict[key] = value
        return original_dict

    # Méthode interne pour obtenir un dictionnaire à partir d'un fichier JSON
    @staticmethod
    def _get_dict_from_json_file(json_file_path: Path) -> dict:
        try:
            json_file_lines = []
            with json_file_path.open("r") as json_file:
                for line in json_file.readlines():
                    if not line.lstrip().startswith("//"):
                        if "    //" in line:
                            json_file_lines.append(line[:line.find("    //")])
                        else:
                            json_file_lines.append(line)
                file_content_as_dict = json.loads("\n".join(json_file_lines))
        except (OSError, json.JSONDecodeError) as e:
            raise UserWarning(f"Load json from file '{json_file_path}' failed: {e}")

        if not isinstance(file_content_as_dict, dict):
            raise UserWarning(f"Json from file '{json_file_path}' is not a dict ({file_content_as_dict})")

        return file_content_as_dict

    # Méthode interne pour écrire un dictionnaire dans un fichier JSON
    @staticmethod
    def _write_dict_to_json_file(input_dict: dict, output_json_file_path: Path) -> NoReturn:
        try:
            with output_json_file_path.open("w", newline="\n") as json_file:
                json.dump(input_dict, json_file, indent=4)
        except (OSError, TypeError, ValueError, OverflowError) as e:
            print(f"Write json to file '{output_json_file_path}' failed: ", e)
            raise UserWarning(f"Write json file '{output_json_file_path}' from dict failed: {e}")

    # Méthode interne pour obtenir le chemin de déploiement
    def _get_deployment_path(self, dict_path: DictPath) -> List[str]:
        deployment_path = []
        for dict_path_step in dict_path.get_dict_path_as_list():
            if dict_path_step in (self.key_words["label_of_a_node_dictionary"], self.key_words["label_of_a_component_dictionary"], self.key_words["label_of_a_component_env_var_dictionary"]):
                continue
            if dict_path_step.startswith(self.key_words["label_of_a_components_group"]):
                deployment_path.append(self._get_group_name_from_definition_key(dict_path_step))
                continue
            deployment_path.append(dict_path_step)
        deployment_path.reverse()
        return deployment_path

    # Méthode interne pour obtenir le chemin du dictionnaire parent du noeud
    def _get_parent_node_dict_path(self, dict_path: DictPath) -> Optional[DictPath]:
        working_dict_path = DictPath(from_dict_path=dict_path)

        while not working_dict_path.is_empty():
            while DictPath.is_a_path_step_as_index(working_dict_path.get_the_last_step_of_the_path()):
                working_dict_path.pop_the_last_step_of_the_path()

            parent_dict_path = working_dict_path.get_the_path_to_parent()
            if parent_dict_path is not None:
                parent_path_step = parent_dict_path.get_the_last_step_of_the_path()
                if parent_path_step == self.key_words["label_of_a_node_dictionary"]:
                    return working_dict_path

            working_dict_path.pop_the_last_step_of_the_path()

        return None

    # Méthode interne pour obtenir les noms des noeuds parents
    def _get_parents_nodes_names(self, dict_path: DictPath) -> Optional[List[str]]:
        parents_nodes_names = []
        working_dict_path = DictPath(from_dict_path=dict_path)

        while not working_dict_path.is_empty():
            while DictPath.is_a_path_step_as_index(working_dict_path.get_the_last_step_of_the_path()):
                working_dict_path.pop_the_last_step_of_the_path()

            last_path_step = working_dict_path.get_the_last_step_of_the_path()
            parent_dict_path = working_dict_path.get_the_path_to_parent()
            if parent_dict_path is not None:
                parent_path_step = parent_dict_path.get_the_last_step_of_the_path()
                if parent_path_step == self.key_words["label_of_a_node_dictionary"]:
                    parents_nodes_names.append(last_path_step)

            working_dict_path.pop_the_last_step_of_the_path()

        return parents_nodes_names
