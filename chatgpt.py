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
# Méthode interne pour obtenir le chemin du dictionnaire parent du groupe de composants
    def _get_parent_component_group_dict_path(self, dict_path: DictPath) -> Optional[DictPath]:
        # Création d'un chemin de travail à partir du chemin donné
        working_dict_path = DictPath(from_dict_path=dict_path)

        # Parcours du chemin de travail
        while not working_dict_path.is_empty():
            # Suppression des index du chemin de travail
            while DictPath.is_a_path_step_as_index(working_dict_path.get_the_last_step_of_the_path()):
                working_dict_path.pop_the_last_step_of_the_path()

            # Récupération de la dernière étape du chemin de travail
            last_path_step = working_dict_path.get_the_last_step_of_the_path()

            # Vérification si la dernière étape du chemin de travail est un dictionnaire de noeud
            if last_path_step == self.key_words["label_of_a_node_dictionary"]:
                return None
            # Vérification si la dernière étape du chemin de travail commence par un groupe de composants
            if last_path_step.startswith(self.key_words["label_of_a_components_group"]):
                return working_dict_path

            # Suppression de la dernière étape du chemin de travail
            working_dict_path.pop_the_last_step_of_the_path()

        return None

    # Méthode interne pour vérifier si le groupe parent est le groupe principal parent
    def _is_parent_group_is_the_main_parent_group(self, dict_path: DictPath) -> bool:
        # Récupération du chemin du dictionnaire parent du groupe de composants
        parent_group_dict_path = self._get_parent_component_group_dict_path(dict_path)

        # Vérification si le chemin du dictionnaire parent est vide
        if parent_group_dict_path is None:
            return False

        # Récupération des étapes du chemin du dictionnaire parent en excluant le premier
        parent_group_dict_path_as_list_without_him = parent_group_dict_path.get_dict_path_as_list()[1:]

        # Parcours des étapes du chemin du dictionnaire parent
        for dict_path_step in parent_group_dict_path_as_list_without_him:
            # Vérification si l'étape du chemin du dictionnaire parent commence par un groupe de composants
            if dict_path_step.startswith(self.key_words["label_of_a_components_group"]):
                return False
        return True

    # Méthode interne pour obtenir le chemin du groupe de composants parent principal
    def _get_main_parent_component_group_dict_path(self, dict_path: DictPath) -> Optional[DictPath]:
        # Création d'un chemin de travail à partir du chemin donné
        working_dict_path = DictPath(from_dict_path=dict_path)

        # Initialisation du candidat pour le chemin du groupe de composants parent principal
        candidate_dict_path = None

        # Parcours du chemin de travail
        while not working_dict_path.is_empty():
            # Suppression des index du chemin de travail
            while DictPath.is_a_path_step_as_index(working_dict_path.get_the_last_step_of_the_path()):
                working_dict_path.pop_the_last_step_of_the_path()

            # Récupération de la dernière étape du chemin de travail
            last_path_step = working_dict_path.get_the_last_step_of_the_path()

            # Vérification si la dernière étape du chemin de travail est un dictionnaire de noeud
            if last_path_step == self.key_words["label_of_a_node_dictionary"]:
                break
            # Vérification si la dernière étape du chemin de travail commence par un groupe de composants
            if last_path_step.startswith(self.key_words["label_of_a_components_group"]):
                # Mise à jour du candidat pour le chemin du groupe de composants parent principal
                candidate_dict_path = DictPath(from_dict_path=working_dict_path)

            # Suppression de la dernière étape du chemin de travail
            working_dict_path.pop_the_last_step_of_the_path()

        return candidate_dict_path

    # Méthode interne pour obtenir les noms des groupes de composants parents
    def _get_parents_component_groups_names(self, dict_path: DictPath) -> Optional[List[str]]:
        # Initialisation de la liste des noms des groupes de composants parents
        parents_component_groups_names = []
        
        # Création d'un chemin de travail à partir du chemin donné
        working_dict_path = DictPath(from_dict_path=dict_path)

        # Parcours du chemin de travail
        while not working_dict_path.is_empty():
            # Suppression des index du chemin de travail
            while DictPath.is_a_path_step_as_index(working_dict_path.get_the_last_step_of_the_path()):
                working_dict_path.pop_the_last_step_of_the_path()

            # Récupération de la dernière étape du chemin de travail
            last_path_step = working_dict_path.get_the_last_step_of_the_path()

            # Récupération du chemin vers le parent du dictionnaire
            parent_dict_path = working_dict_path.get_the_path_to_parent()

            # Vérification si le chemin vers le parent du dictionnaire existe
            if parent_dict_path is not None:
                # Vérification si la dernière étape du chemin de travail commence par un groupe de composants
                if last_path_step.startswith(self.key_words["label_of_a_components_group"]):
                    # Ajout du nom du groupe de composants parent à la liste
                    parents_component_groups_names.append(self._get_group_name_from_definition_key(last_path_step))

            # Suppression de la dernière étape du chemin de travail
            working_dict_path.pop_the_last_step_of_the_path()

        return parents_component_groups_names

    # Méthode interne pour obtenir le nom du groupe à partir de la clé de définition du groupe
    def _get_group_name_from_definition_key(self, group_name_definition_key):
        return group_name_definition_key[group_name_definition_key.find(self.key_words["label_of_a_components_group"]) + len(self.key_words["label_of_a_components_group"]):]

    # Méthode interne pour rechercher par chemin de déploiement
    def _search_by_deployment_path(self, parameter_deployment_path_as_string: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> Tuple[Optional[Union[str, int, float, bool, list, dict]], Optional[dict], Optional[DictPath]]:
        # Séparation du chemin de déploiement en une liste de pas
        working_parameter_path = parameter_deployment_path_as_string.split("/")

        # Récupération du premier pas du chemin de déploiement
        first_relative_deployment_path_step = working_parameter_path[0]

        # Recherche du premier pas du chemin de déploiement
        _, _, first_relative_deployment_path_step_parent_dict_path = self._search_from_here_to_the_top_of_the_parameter_value(first_relative_deployment_path_step, dict_path, path_based_dict)
        
        # Vérification si le premier pas du chemin de déploiement a été trouvé
        if first_relative_deployment_path_step_parent_dict_path is None:
            potential_component_group_name = self.key_words["label_of_a_components_group"] + first_relative_deployment_path_step
            _, _, first_relative_deployment_path_step_parent_dict_path = self._search_from_here_to_the_top_of_the_parameter_value(potential_component_group_name, dict_path, path_based_dict)
            if first_relative_deployment_path_step_parent_dict_path is None:
                raise UserWarning(f"The '{dict_path}' parameter reference '{first_relative_deployment_path_step}' not found")

        dict_path = first_relative_deployment_path_step_parent_dict_path
        param_value = None
        param_parent_dict = None

        # Parcours de la liste des pas du chemin de déploiement
        while len(working_parameter_path) > 0:
            node_or_component_group_or_component_name = working_parameter_path[0]
            potential_component_group_name = self.key_words["label_of_a_components_group"] + node_or_component_group_or_component_name

            param_parent_dict = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path)
            if not isinstance(param_parent_dict, dict):
                return None, None, None

            if node_or_component_group_or_component_name in param_parent_dict:
                working_parameter_path.pop(0)
                param_value = param_parent_dict.get(node_or_component_group_or_component_name, None)
                dict_path = dict_path.get_the_path_to_a_following_step(node_or_component_group_or_component_name)
                continue
            elif potential_component_group_name in param_parent_dict:
                working_parameter_path.pop(0)
                param_value = param_parent_dict.get(potential_component_group_name, None)
                dict_path = dict_path.get_the_path_to_a_following_step(potential_component_group_name)
                continue
            elif self.key_words["label_of_a_node_dictionary"] in param_parent_dict:
                dict_path = dict_path.get_the_path_to_a_following_step(self.key_words["label_of_a_node_dictionary"])
                continue
            elif self.key_words["label_of_a_component_dictionary"] in param_parent_dict:
                dict_path = dict_path.get_the_path_to_a_following_step(self.key_words["label_of_a_component_dictionary"])
                continue
            elif self.key_words["label_of_a_component_env_var_dictionary"] in param_parent_dict:
                dict_path = dict_path.get_the_path_to_a_following_step(self.key_words["label_of_a_component_env_var_dictionary"])
                continue
            else:
                return None, None, None

        return param_value, param_parent_dict, dict_path

    # Méthode statique pour rechercher de cet endroit au sommet de la valeur du paramètre
    @staticmethod
    def _search_from_here_to_the_top_of_the_parameter_value(parameter: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> Tuple[Optional[Union[str, int, float, bool, list, dict]], Optional[dict], Optional[DictPath]]:
        # Fonction interne pour rechercher la valeur du paramètre dans l'étape du chemin
        def search_parameter_value_in_path_step(dict_path_to_check: DictPath, last_key_checked: str = None) -> Tuple[Optional[Union[str, int, float, bool, list, dict]], Optional[dict], Optional[DictPath]]:
            path_value = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path_to_check)
            if not isinstance(path_value, dict):
                return None, None, None

            param_value = path_value.get(parameter, None)
            if param_value is not None:
                return param_value, path_value, dict_path_to_check

            key_list = list(path_value.keys())
            if last_key_checked is None or last_key_checked not in path_value.keys():
                pass
            else:
                key_list = key_list[:key_list.index(last_key_checked)]
                key_list.reverse()

            for key in key_list:
                param_value, param_parent_dict, dict_path_to_param_parent_dict = search_parameter_value_in_path_step(dict_path_to_check.get_the_path_to_a_following_step(key))
                if param_value is not None:
                    return param_value, param_parent_dict, dict_path_to_param_parent_dict

            return None, None, None

        # Création d'un chemin de travail à partir du chemin donné
        working_dict_path = DictPath(from_dict_path=dict_path)
        last_dict_key_checked = None

        # Parcours du chemin de travail
        while not working_dict_path.is_empty():
            # Suppression des index du chemin de travail
            while DictPath.is_a_path_step_as_index(working_dict_path.get_the_last_step_of_the_path()):
                working_dict_path.pop_the_last_step_of_the_path()

            # Recherche de la valeur du paramètre dans l'étape du chemin
            parameter_value, parameter_parent_dict, dict_path_to_parameter_parent_dict = search_parameter_value_in_path_step(working_dict_path, last_dict_key_checked)
            if parameter_value is not None:
                return parameter_value, parameter_parent_dict, dict_path_to_parameter_parent_dict

            last_dict_key_checked = working_dict_path.pop_the_last_step_of_the_path()
        else:
            parameter_value, parameter_parent_dict, dict_path_to_parameter_parent_dict = search_parameter_value_in_path_step(working_dict_path, last_dict_key_checked)
            if parameter_value is not None:
                return parameter_value, parameter_parent_dict, dict_path_to_parameter_parent_dict

        return None, None, None

class DeploymentDescriptionCleaner(DeploymentDescriptionParser):

    # Méthode pour nettoyer le dictionnaire de description de déploiement
    def clean_deployment_description_dict(self, deployment_description_dict: dict) -> NoReturn:
        # Appel de la méthode de parsing pour analyser et nettoyer le dictionnaire de description de déploiement
        self.parse_deployment_description_dict(deployment_description_dict)

    # Méthode interne pour traiter le début de la clé
    def _process_key_starting(self, new_key_in_the_path: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> Optional[str]:
        # Récupération du chemin parent et du grand-parent de la clé
        parent_path_step = dict_path.get_the_last_step_of_the_path()
        great_parent_path_step = dict_path.get_the_path_to_parent()
        if great_parent_path_step is not None:
            great_parent_path_step = great_parent_path_step.get_the_last_step_of_the_path()

        # Suppression de la clé si elle est au plus haut niveau et n'est pas un mot-clé du parseur de description de déploiement
        if parent_path_step is None:
            if not self.is_a_deployment_description_parser_key_word(new_key_in_the_path):
                return DictionaryParser.DELETE_THE_KEY

        # Suppression de la clé si elle est une définition de modèle de composant
        if self.key_words["label_of_a_template_definition"] in new_key_in_the_path:
            return DictionaryParser.DELETE_THE_KEY

        # Suppression de la clé si elle est dans le dictionnaire de nœud et n'est pas un mot-clé du parseur de description de déploiement
        if great_parent_path_step == self.key_words["label_of_a_node_dictionary"]:
            if not self.is_a_deployment_description_parser_key_word(new_key_in_the_path):
                return DictionaryParser.DELETE_THE_KEY

        # Suppression de la clé si elle est dans le groupe de composants et n'est pas un mot-clé du parseur de description de déploiement
        if isinstance(parent_path_step, str) and parent_path_step.startswith(self.key_words["label_of_a_components_group"]):
            if not self.is_a_deployment_description_parser_key_word(new_key_in_the_path):
                return DictionaryParser.DELETE_THE_KEY

        # Suppression de la clé si elle est dans le dictionnaire de composant et n'est pas un mot-clé du parseur de description de déploiement
        if great_parent_path_step == self.key_words["label_of_a_component_dictionary"]:
            if not self.is_a_deployment_description_parser_key_word(new_key_in_the_path):
                return DictionaryParser.DELETE_THE_KEY

        # Ignorer la clé si elle est dans la section PEL
        if parent_path_step == self.key_words["label_of_a_pel_section"]:
            return DictionaryParser.IGNORE_THE_KEY

        # Ignorer la clé si elle est dans la section PIL
        if parent_path_step == self.key_words["label_of_a_pil_section"]:
            return DictionaryParser.IGNORE_THE_KEY

        # Ignorer la clé si elle est dans la section Jaeger
        if parent_path_step == self.key_words["label_of_a_jaeger_section"]:
            return DictionaryParser.IGNORE_THE_KEY

        # Conserver la clé
        return new_key_in_the_path

    # Méthode interne pour traiter la fin de la clé
    def _process_key_ending(self, new_key_in_the_path: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        # Ne rien faire à la fin de la clé
        pass

    # Méthode interne pour traiter la valeur finale
    def _process_final_value(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> bool:
        # Aucune mise à jour de valeur n'a été effectuée
        is_value_updated = False
        return is_value_updated

class DeploymentDescriptionBuilder(DeploymentDescriptionParser):

    # Constructeur de la classe
    def __init__(self, component_config_dir_path: Path = None):
        # Appel du constructeur de la classe parente
        DeploymentDescriptionParser.__init__(self)

        # Initialisation du chemin du répertoire de configuration des composants
        self.componentConfigDirPath = component_config_dir_path

    # Méthode pour analyser une description de déploiement depuis un fichier JSON et écrire le résultat dans un autre fichier JSON
    def parse_deployment_description_from_json_file_to_json_file(self, json_file_path_source: Path, deployment_target: str, json_file_path_destination: Path) -> NoReturn:
        # Extraction du dictionnaire de description de déploiement à partir du fichier source JSON
        deployment_dict = self._get_dict_from_json_file(json_file_path_source)

        # Ajout de l'étiquette de la cible de déploiement dans le dictionnaire
        deployment_dict[self.key_words["label_of_the_deployment_target"]] = deployment_target

        # Analyse et nettoyage du dictionnaire de description de déploiement
        self.parse_deployment_description_dict(deployment_dict)

        # Création du répertoire parent pour le fichier de destination s'il n'existe pas
        json_file_path_destination.parent.mkdir(parents=True, exist_ok=True)
        # Suppression du fichier de destination s'il existe déjà
        if json_file_path_destination.exists():
            json_file_path_destination.unlink()

        # Nettoyage supplémentaire du dictionnaire de description de déploiement
        deployment_description_cleaner = DeploymentDescriptionCleaner()
        deployment_description_cleaner.clean_deployment_description_dict(deployment_dict)
        # Écriture du dictionnaire nettoyé dans le fichier JSON de destination
        self._write_dict_to_json_file(deployment_dict, json_file_path_destination)

    # Méthode interne pour traiter le début de la clé
    def _process_key_starting(self, new_key_in_the_path: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> Optional[str]:
        # Récupération de l'étape parente du chemin
        parent_path_step = dict_path.get_the_last_step_of_the_path()

        # Suppression de la clé si elle commence par un marqueur de suppression
        if new_key_in_the_path.startswith("! "):
            return DictionaryParser.DELETE_THE_KEY

        # Suppression de la partie conditionnelle de la clé si présente
        if self.key_words["label_of_is_present_test"] in new_key_in_the_path:
            new_key = self._replace_conditional_key(new_key_in_the_path, dict_path, path_based_dict)
            if new_key is None:
                return DictionaryParser.DELETE_THE_KEY
        else:
            new_key = self._replace_referenced_key(new_key_in_the_path, dict_path, path_based_dict)

        # Remplacement de la clé avec un template
        if self.key_words["label_of_a_template_use"] in new_key:
            new_key = self._replace_templated_key(new_key, dict_path, path_based_dict)

        # Ajout du nom de nœud si nécessaire
        if parent_path_step == self.key_words["label_of_a_node_dictionary"]:
            for path_step in dict_path.get_dict_path_as_list():
                if self.key_words["label_of_a_components_group"] in path_step or self.key_words["label_of_a_component_dictionary"] in path_step:
                    raise UserWarning(f"The '{dict_path}' to the key '{new_key}' contains component group or component dictionary")

            self._add_node_name_key(new_key, dict_path, path_based_dict)

        # Ajout du nom du groupe de composants si nécessaire
        if new_key.startswith(self.key_words["label_of_a_components_group"]):
            self._add_component_group_name_key(new_key, dict_path, path_based_dict)

        # Ajout du nom du composant si nécessaire
        if parent_path_step == self.key_words["label_of_a_component_dictionary"]:
            if not self.is_a_correct_node_or_component_name(new_key_in_the_path):
                raise UserWarning(f"The '{dict_path}' key '{new_key}' is not a component name")

            self._add_component_description_name_key(new_key, dict_path, path_based_dict)
            if self.componentConfigDirPath is not None:
                self._check_component_description_name_key(new_key, dict_path, path_based_dict)

        return new_key

    # Méthode interne pour traiter la fin de la clé
    def _process_key_ending(self, new_key_in_the_path: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        # Ne rien faire à la fin de la clé
        pass

    # Méthode interne pour traiter la valeur finale
    def _process_final_value(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> bool:
        # Aucune mise à jour de valeur n'a été effectuée
        is_value_updated = False
        # Remplacement des valeurs de clés référencées
        is_value_updated |= self._replace_templated_final_value(dict_path, path_based_dict)
        is_value_updated |= self._replace_referenced_final_value(dict_path, path_based_dict)
        return is_value_updated

    # Méthode interne pour remplacer une clé référencée
    def _replace_referenced_key(self, referenced_key: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> str:
        # Remplacement des références dans la clé
        new_key = self._replace_references_in_value(referenced_key, dict_path, path_based_dict)
        # Si la clé reste inchangée, retourner la clé d'origine
        if new_key == referenced_key:
            return referenced_key

        # Obtenir le chemin de dictionnaire vers la clé référencée
        dict_path_to_referenced_key = dict_path.get_the_path_to_a_following_step(referenced_key)
        # Remplacer la dernière clé du chemin par la nouvelle clé
        path_based_dict.replace_the_last_key_given_by_a_dict_path(dict_path_to_referenced_key, new_key)
        return new_key

    # Méthode interne pour remplacer la valeur finale référencée
    def _replace_referenced_final_value(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> bool:
        # Récupérer la valeur référencée à partir du chemin du dictionnaire
        referenced_value = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path)
        # Vérifier si la valeur est une chaîne
        if not isinstance(referenced_value, str):
            return False

        # Remplacement des références dans la valeur
        new_value = self._replace_references_in_value(referenced_value, dict_path, path_based_dict)
        # Si la valeur reste inchangée, retourner False
        if new_value == referenced_value:
            return False

        # Définir la nouvelle valeur dans le chemin du dictionnaire
        path_based_dict.set_the_value_pointed_by_a_dict_path(new_value, dict_path)

        return True

    # Méthode interne pour remplacer une clé avec un modèle
    def _replace_templated_key(self, templated_key: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> str:
        # Obtenir le chemin de dictionnaire vers la clé modèle
        dict_path_to_templated_key = dict_path.get_the_path_to_a_following_step(templated_key)
        # Récupérer la valeur actuelle de la clé modèle
        current_value = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path_to_templated_key)
        # Extraire le nom de la clé à partir de la clé modèle
        new_key = templated_key[:templated_key.find(self.key_words["label_of_a_template_use"])]
        # Extraire le nom du modèle à partir de la clé modèle
        template_to_use = templated_key[templated_key.find(self.key_words["label_of_a_template_use"]):]
        template_name = self.key_words["label_of_a_template_definition"] + template_to_use[len(self.key_words["label_of_a_template_use"]):]
        # Vérifier si le modèle est défini
        if len(template_name) == 0:
            raise UserWarning(f"The '{dict_path}' template in key '{templated_key}' not defined")

        # Remplacer les références dans le nom du modèle
        referenced_template_name = self._replace_references_in_value(template_name, dict_path, path_based_dict)

        # Rechercher la valeur du modèle dans le dictionnaire
        template_value, _, _ = self._search_from_here_to_the_top_of_the_parameter_value(referenced_template_name, dict_path, path_based_dict)
        # Vérifier si le modèle est trouvé
        if template_value is None:
            raise UserWarning(f"The '{dict_path}' template in key '{templated_key}' not found")

        # Copier la valeur du modèle
        new_value = copy.deepcopy(template_value)

        # Fusionner les valeurs si les deux sont des dictionnaires
        if isinstance(new_value, dict) and isinstance(current_value, dict):
            self._deep_update(new_value, current_value)

        # Remplacer la clé modèle par la nouvelle clé et sa valeur
        path_based_dict.replace_the_last_key_given_by_a_dict_path(dict_path_to_templated_key, new_key, new_value)

        return new_key

    # Méthode interne pour remplacer la valeur finale avec un modèle
    def _replace_templated_final_value(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> bool:
        # Récupérer la valeur finale référencée à partir du chemin du dictionnaire
        templated_value = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path)
        # Vérifier si la valeur est une chaîne et commence par l'étiquette de modèle
        if not isinstance(templated_value, str) or not templated_value.startswith(f"{self.key_words['label_of_a_template_use']}"):
            return False

        # Extraire le nom du modèle à partir de la valeur
        template_to_use = templated_value[templated_value.find(self.key_words["label_of_a_template_use"]):]
        template_name = self.key_words["label_of_a_template_definition"] + template_to_use[len(self.key_words["label_of_a_template_use"]):]
        # Vérifier si le modèle est défini
        if len(template_name) == 0:
            raise UserWarning(f"The '{dict_path}' template in value '{templated_value}' not defined")

        # Remplacer les références dans le nom du modèle
        referenced_template_name = self._replace_references_in_value(template_name, dict_path, path_based_dict)

        # Rechercher la valeur du modèle dans le dictionnaire
        template_value, _, _ = self._search_from_here_to_the_top_of_the_parameter_value(referenced_template_name, dict_path, path_based_dict)
        # Vérifier si le modèle est trouvé
        if template_value is None:
            raise UserWarning(f"The '{dict_path}' template in value '{templated_value}' not found")

        # Copier la valeur du modèle
        new_value = copy.deepcopy(template_value)
        # Définir la nouvelle valeur dans le chemin du dictionnaire
        path_based_dict.set_the_value_pointed_by_a_dict_path(new_value, dict_path)

        return True

    # Méthode interne pour ajouter une clé de nom de nœud
    def _add_node_name_key(self, node_definition_key: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        # Obtenir le chemin de dictionnaire vers la clé de définition de nœud
        dict_path_to_node_definition_key = dict_path.get_the_path_to_a_following_step(node_definition_key)
        # Récupérer la valeur actuelle de la clé de définition de nœud
        current_value = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path_to_node_definition_key)
        # Vérifier si la valeur est un dictionnaire
        if not isinstance(current_value, dict):
            raise UserWarning(f"The '{dict_path}' node '{node_definition_key}' is not a dict as value type")

        # Vérifier si la clé de nom de nœud est déjà définie
        if self.key_words["label_of_the_node_name"] in current_value.keys():
            raise UserWarning(f"The '{dict_path}' node '{node_definition_key}' already defined a '{self.key_words['label_of_the_node_name']}'")

        # Ajouter la clé de nom de nœud avec la valeur actuelle dans le dictionnaire
        new_node_definition_value = {self.key_words["label_of_the_node_name"]: node_definition_key, **current_value}
        path_based_dict.set_the_value_pointed_by_a_dict_path(new_node_definition_value, dict_path_to_node_definition_key)

    # Méthode interne pour ajouter une clé de nom de groupe de composants
    def _add_component_group_name_key(self, group_name_definition_key: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        # Obtenir le chemin de dictionnaire vers la clé de définition de nom de groupe
        dict_path_to_group_name_definition_key = dict_path.get_the_path_to_a_following_step(group_name_definition_key)
        # Récupérer la valeur actuelle de la clé de définition de nom de groupe
        current_value = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path_to_group_name_definition_key)
        # Vérifier si la valeur est un dictionnaire
        if not isinstance(current_value, dict):
            raise UserWarning(f"The '{dict_path}' component group defined in key '{group_name_definition_key}' has not a dict as value type")

        # Extraire le nom du groupe à partir de la clé de définition de nom de groupe
        group_name = self._get_group_name_from_definition_key(group_name_definition_key)
        # Vérifier si le nom du groupe est défini
        if group_name == "":
            raise UserWarning(f"The '{dict_path}' component group defined in key '{group_name_definition_key}' has no component group name defined")

        # Vérifier si la clé de nom de groupe de composants est déjà définie
        if self.key_words["label_of_the_components_group_name"] in current_value:
            raise UserWarning(f"The '{dict_path}' component group name '{group_name}' already defined a '{self.key_words['label_of_the_components_group_name']}'")

        # Ajouter la clé de nom de groupe de composants avec la valeur actuelle dans le dictionnaire
        new_group_definition_value = {self.key_words["label_of_the_components_group_name"]: group_name, **current_value}
        path_based_dict.set_the_value_pointed_by_a_dict_path(new_group_definition_value, dict_path_to_group_name_definition_key)

    # Méthode interne pour ajouter une clé de nom de description de composant
    def _add_component_description_name_key(self, component_description_definition_key: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        # Obtenir le chemin de dictionnaire vers la clé de définition de description de composant
        dict_path_to_component_description_definition_key = dict_path.get_the_path_to_a_following_step(component_description_definition_key)
        # Récupérer la valeur actuelle de la clé de définition de description de composant
        current_value = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path_to_component_description_definition_key)
        # Vérifier si la valeur est un dictionnaire
        if not isinstance(current_value, dict):
            raise UserWarning(f"The '{dict_path}' component description '{component_description_definition_key}' is not a dict as value type")

        # Vérifier si la clé de nom de description de composant est déjà définie
        if self.key_words["label_of_the_component_description_name"] in current_value.keys():
            raise UserWarning(f"The '{dict_path}' component description '{component_description_definition_key}' already defined a '{self.key_words['label_of_the_component_description_name']}'")

        # Vérifier si la clé de nom de composant est définie dans le dictionnaire
        if self.key_words["label_of_the_component_name"] not in current_value.keys():
            raise UserWarning(f"The '{dict_path}' component description '{component_description_definition_key}' doesn't define a '{self.key_words['label_of_the_component_name']}'")

        # Vérifier si la clé de dictionnaire de variables d'environnement du composant est définie dans le dictionnaire
        if self.key_words["label_of_a_component_env_var_dictionary"] not in current_value.keys():
            raise UserWarning(f"The '{dict_path}' component description '{component_description_definition_key}' doesn't define a '{self.key_words['label_of_the_component_name']}'")

        # Ajouter la clé de nom de description de composant avec la valeur actuelle dans le dictionnaire
        new_component_description_value = {self.key_words["label_of_the_component_description_name"]: component_description_definition_key, **current_value}
        path_based_dict.set_the_value_pointed_by_a_dict_path(new_component_description_value, dict_path_to_component_description_definition_key)

    # Méthode interne pour vérifier la clé de nom de description de composant
    def _check_component_description_name_key(self, component_description_definition_key: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        # Obtenir le chemin de dictionnaire vers la clé de définition de description de composant
        dict_path_to_component_description_definition_key = dict_path.get_the_path_to_a_following_step(component_description_definition_key)
        # Récupérer la valeur actuelle de la clé de définition de description de composant
        current_value = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path_to_component_description_definition_key)
        # Récupérer le nom du composant référencé
        component_deployment_name = "/".join(self._get_deployment_path(dict_path))

        # Récupérer le nom du composant
        component_name = current_value.get(self.key_words["label_of_the_component_name"], None)
        # Remplacer les références dans le nom du composant
        referenced_component_name = self._replace_references_in_value(component_name, dict_path_to_component_description_definition_key, path_based_dict)
        # Récupérer le dictionnaire de variables d'environnement du composant
        component_env_var_dictionary = current_value.get(self.key_words["label_of_a_component_env_var_dictionary"], None)
        # Créer une copie du dictionnaire de variables d'environnement du composant sans le mot-clé de test de présence
        component_env_var_dictionary_without_key_word = {k if self.key_words["label_of_is_present_test"] not in k else k[:k.find(self.key_words["label_of_is_present_test"])]: v for (k, v) in component_env_var_dictionary.items()}

        # Récupérer les valeurs de configuration du composant à partir du fichier equinox.sh
        equinox_sh_value_by_component_parameter_name, additional_equinox_sh_value_by_component_parameter_name = self._get_component_configuration_from_config_equinox_sh(referenced_component_name)

        # Extraire les paramètres supplémentaires de equinox.sh
        additional_equinox_sh_parameter = set()
        for additional_parameters_list in additional_equinox_sh_value_by_component_parameter_name.values():
            additional_equinox_sh_parameter = additional_equinox_sh_parameter.union(set(additional_parameters_list))

        # Vérifier si le dictionnaire de variables d'environnement du composant contient une clé spécifique
        if "!!! FILLED AT BUILDING TIME !!!" in component_env_var_dictionary:
            print(f"     !! Build warning: the '{component_deployment_name}' ('{referenced_component_name}') component description was filled from equinox content")

            # Remplacer les paramètres du composant par ceux de equinox.sh
            component_parameters_dict = equinox_sh_value_by_component_parameter_name

            for component_parameter, additional_parameters in additional_equinox_sh_value_by_component_parameter_name.items():
                for additional_parameter in additional_parameters:
                    component_parameters_dict[additional_parameter] = f"associated to '{component_parameter}'"

            component_env_var_dictionary.clear()
            component_env_var_dictionary.update(component_parameters_dict)
        else:
            # Vérifier les erreurs et avertissements liés aux paramètres du composant
            for parameter_name in component_env_var_dictionary_without_key_word.keys():
                if parameter_name not in equinox_sh_value_by_component_parameter_name:
                    if parameter_name in additional_equinox_sh_parameter:
                        print(f"     !! Build warning: the '{component_deployment_name}' ('{referenced_component_name}') component description"
                              f" defines the unexpected environment variable '{parameter_name}' but it seems that it is an additional equinox parameter")
                    else:
                        print(f"     !! Build error: the '{component_deployment_name}' ('{referenced_component_name}') component description"
                              f" defines the unexpected environment variable '{parameter_name}'")

            for parameter_name, parameter_value in equinox_sh_value_by_component_parameter_name.items():
                if "TO_BE_DEFINED" in parameter_value:
                    if parameter_name not in component_env_var_dictionary_without_key_word:
                        print(f"     !! Build error: the '{component_deployment_name}' ('{referenced_component_name}') component description"
                              f" doesn't define the expected environment variable '{parameter_name}'")
                else:
                    if parameter_name in component_env_var_dictionary_without_key_word and str(parameter_value) == str(component_env_var_dictionary_without_key_word[parameter_name]):
                        print(f"     !! Build warning: the '{component_deployment_name}' ('{referenced_component_name}') component description"
                              f" define the variable '{parameter_name}' at its default value ('{parameter_value}')")

                    if parameter_name not in component_env_var_dictionary_without_key_word:
                        component_env_var_dictionary.update({f"DEFAULT VALUE OF '{parameter_name}'": parameter_value})

            for parameter_name in additional_equinox_sh_parameter:
                if parameter_name not in component_env_var_dictionary_without_key_word:
                    print(f"     !! Build warning: the '{component_deployment_name}' ('{referenced_component_name}') component description"
                          f" doesn't define the additional environment variable '{parameter_name}' (often for mock component)")

        # Définir la valeur actuelle dans le chemin du dictionnaire
        path_based_dict.set_the_value_pointed_by_a_dict_path(current_value, dict_path_to_component_description_definition_key)

def _replace_references_in_value(self, value: Union[str, int, float, bool, list, dict], dict_path: DictPath, path_based_dict: PathBasedDictionary) -> Optional[Union[str, int, float, bool, list, dict]]:
        """
        Remplace les références et évalue les expressions dans la valeur donnée.

        Args:
            value (Union[str, int, float, bool, list, dict]): La valeur à traiter.
            dict_path (DictPath): Le chemin vers l'entrée actuelle du dictionnaire.
            path_based_dict (PathBasedDictionary): La structure de dictionnaire contenant les valeurs.

        Returns:
            Optional[Union[str, int, float, bool, list, dict]]: La valeur traitée.

        """
        output_value = value

        # Remplacer les références sur les paramètres
        output_value = self._replace_references_on_parameter_in_value(output_value, dict_path, path_based_dict)

        # Mettre en place un dictionnaire locals sécurisé pour l'évaluation
        safe_locals_dict_to_use = {
            "wp": dict_path.get_dict_path_as_list(),
        }

        # Remplacer les références sur les lambdas
        output_value = self._replace_references_on_lambdas_in_value(output_value, dict_path, path_based_dict, safe_locals_dict=safe_locals_dict_to_use)
        output_value = self._replace_references_on_evaluations_in_value(output_value, safe_locals_dict=safe_locals_dict_to_use)

        # Arrêter si la valeur n'a pas changé
        if output_value == value:
            return value

        # Effectuer une dernière évaluation pour restaurer le type de valeur bool, int...
        try:
            final_eval_result = eval(output_value, {"__builtins__": None}, {})
        except (SyntaxError, NameError, TypeError):
            # Possiblement la chaîne à évaluer est une chaîne finale à cette étape
            pass
        else:
            if type(final_eval_result) != tuple:  # "a, b" est considéré comme un tuple (a, b)
                output_value = final_eval_result

        return output_value

    def _replace_references_on_parameter_in_value(self, value: Union[str, int, float, bool, list, dict], dict_path: DictPath, path_based_dict: PathBasedDictionary, max_number_of_loop=10) -> Optional[Union[str, int, float, bool, list, dict]]:
        """
        Remplace les références sur les paramètres dans la valeur donnée.

        Args:
            value (Union[str, int, float, bool, list, dict]): La valeur à traiter.
            dict_path (DictPath): Le chemin vers l'entrée actuelle du dictionnaire.
            path_based_dict (PathBasedDictionary): La structure de dictionnaire contenant les valeurs.
            max_number_of_loop (int, facultatif): Nombre maximum de boucles pour les références imbriquées. Par défaut à 10.

        Returns:
            Optional[Union[str, int, float, bool, list, dict]]: La valeur traitée.
        """
        if not isinstance(value, str):
            return value

        output_value = value
        loop_count = 0
        while loop_count < max_number_of_loop:
            loop_count += 1

            # Trouver toutes les références de paramètres dans la valeur
            referenced_parameters = re.findall(r"\${((?:(?!\${).)*?)}", output_value, re.MULTILINE)
            if len(referenced_parameters) == 0:
                break

            # Remplacer chaque référence de paramètre par sa valeur
            for referenced_parameter in referenced_parameters:
                if "/" in referenced_parameter:
                    parameter_value, _, _ = self._search_by_deployment_path(referenced_parameter, dict_path, path_based_dict)
                else:
                    parameter_value, _, _ = self._search_from_here_to_the_top_of_the_parameter_value(referenced_parameter, dict_path, path_based_dict)
                if parameter_value is None:
                    raise UserWarning(f"La référence de paramètre '{referenced_parameter}' de '{dict_path}' n'a pas été trouvée")
                output_value = output_value.replace(f"${{{referenced_parameter}}}", str(parameter_value))
        else:
            raise UserWarning(f"La référence de '{dict_path}' n'a pas été remplacée avant le nombre maximum de boucles autorisé")

        return output_value

    # noinspection GrazieInspection
    def _replace_references_on_lambdas_in_value(self, value: Union[str, int, float, bool, list, dict], dict_path: DictPath, path_based_dict: PathBasedDictionary, safe_globals_dict: dict = None, safe_locals_dict: dict = None, max_number_of_loop=10) -> Optional[Union[str, int, float, bool, list, dict]]:
        """
        Évalue les expressions lambda référencées dans la valeur donnée.

        Args:
            value (Union[str, int, float, bool, list, dict]): La valeur à traiter.
            dict_path (DictPath): Le chemin vers l'entrée actuelle du dictionnaire.
            path_based_dict (PathBasedDictionary): La structure de dictionnaire contenant les valeurs.
            safe_globals_dict (dict, facultatif): Dictionnaire global sécurisé pour l'évaluation. Par défaut à None.
            safe_locals_dict (dict, facultatif): Dictionnaire local sécurisé pour l'évaluation. Par défaut à None.
            max_number_of_loop (int, facultatif): Nombre maximum de boucles pour les références imbriquées. Par défaut à 10.

        Returns:
            Optional[Union[str, int, float, bool, list, dict]]: La valeur traitée.
        """
        if not isinstance(value, str):
            return value

        if safe_globals_dict is None:
            safe_globals_dict = {}
        if safe_locals_dict is None:
            safe_locals_dict = {}

        output_value = value
        loop_count = 0
        while loop_count < max_number_of_loop:
            loop_count += 1

            # Trouver toutes les expressions lambda dans la valeur
            lambda_tuples = re.findall(r"<<([A-Za-z0-9.\-_, ]*)([:=]+?)([A-Za-z0-9.\-_+ \"'()\[\]:{}]*?)>>", output_value, re.MULTILINE)
            if len(lambda_tuples) == 0:
                break
            # Parcourir chaque expression lambda
            for lambda_tuple in lambda_tuples:
                if isinstance(lambda_tuple, tuple) and len(lambda_tuple) != 3:
                    raise UserWarning(f"La commande '{lambda_tuple}' était inattendue")
                current_value = output_value
                parameters_name_string = lambda_tuple[0]
                parameters_name_tuple = lambda_tuple[0].split(",")
                result_destination = lambda_tuple[1]
                lambda_string = lambda_tuple[2]

                # Recherche des références de paramètres de lambda
                parameters_values = {}
                parameters_parent_dic = {}
                for parameter_name in parameters_name_tuple:
                    parameter_name = parameter_name.strip()
                    parameter_value, parameter_parent_dict, _ = self._search_from_here_to_the_top_of_the_parameter_value(parameter_name, dict_path, path_based_dict)
                    if parameter_value is None:
                        raise UserWarning(f"Le paramètre '{parameter_name}' de '{dict_path}' n'a pas été trouvé")

                    parameters_values[parameter_name] = parameter_value
                    parameters_parent_dic[parameter_name] = parameter_parent_dict

                # Construire les arguments lambda comme a, b, c...
                abc_string = ",".join(list(string.ascii_lowercase[:len(parameters_name_tuple)]))
                evaluation_string = f"lambda {abc_string}: {lambda_string}"

                # Évaluer l'expression lambda
                try:
                    safe_locals_dict_to_use = {}
                    safe_locals_dict_to_use.update(safe_locals_dict)

                    safe_global_dict_to_use = {
                        "__builtins__": {
                            "int": int,
                            "str": str,
                            "range": range,
                            "enumerate": enumerate,
                            "len": len,
                        }
                    }
                    safe_global_dict_to_use.update(safe_globals_dict)

                    lambda_function = eval(evaluation_string, safe_global_dict_to_use, safe_locals_dict_to_use)
                except (NameError, TypeError, SyntaxError) as e:
                    raise UserWarning(f"L'évaluation ('''{evaluation_string}''') a échoué : {e}")

                # Appliquer la fonction lambda
                lambda_result = lambda_function(*parameters_values.values())

                # Affecter ou non les résultats de la fonction lambda
                if result_destination.startswith("="):
                    parameters_parent_dic[parameters_name_tuple[0].strip()][parameters_name_tuple[0].strip()] = lambda_result

                # Remplacer le motif lambda pour la boucle suivante
                rebuilt_string = f"<<{parameters_name_string}{result_destination}{lambda_string}>>"
                output_value = current_value.replace(rebuilt_string, str(lambda_result))
                # make_final_evaluation = True
        else:
            raise UserWarning(f"La référence de '{dict_path}' n'a pas été remplacée avant le nombre maximum de boucles autorisé")

        # if make_final_evaluation:
        #     try:
        #         final_eval_result = eval(output_value, {"__builtins__": None}, {})
        #     except (SyntaxError, NameError, TypeError):
        #         # Possiblement la chaîne à évaluer est une chaîne finale à cette étape
        #         pass
        #     else:
        #         output_value = final_eval_result

        return output_value

def _get_component_configuration_from_config_equinox_sh(self, component_name: str) -> Tuple[dict, dict]:
        """
        Récupère la configuration du composant à partir du fichier equinox.sh.

        Args:
            component_name (str): Le nom du composant.

        Returns:
            Tuple[dict, dict]: Un tuple contenant deux dictionnaires, le premier pour les valeurs des paramètres équinox,
            et le second pour les paramètres équinox supplémentaires.
        """
        component_equinox_source_file_path = self.componentConfigDirPath / component_name / "equinox.sh"

        opt_file_lines = []
        try:
            with component_equinox_source_file_path.open("r") as sh_file:
                for line in sh_file.readlines():
                    if line.lstrip().startswith("OPT_"):
                        opt_file_lines.append(line)
        except OSError as e:
            raise UserWarning(f"La lecture du contenu du fichier '{component_equinox_source_file_path.relative_to(self.componentConfigDirPath)}' a échoué : {e}")

        equinox_parameter_value_by_component_parameter_name = {}
        additional_equinox_parameter_by_component_parameter_name = {}
        equinox_parameter_name_by_component_parameter_name = {}
        for opt_line in opt_file_lines:
            opt_line = opt_line.replace('"', '<double-quote>')
            opt_line = opt_line.replace('\\', '<back-slash>')

            pattern = 'OPT_(?P<equinox_parameter_name>\w*)=\${(?P<component_parameter_name>\w*)(?P<character_column>:?)-(?P<equinox_component_parameter_value>.*)}'
            parameter_name_and_default_value_math = re.match(pattern, opt_line.strip())
            if parameter_name_and_default_value_math is not None:
                character_column = parameter_name_and_default_value_math.group("character_column")
                if character_column == "":
                    print(f"     !! Vérifiez la liste des paramètres du composant dans equinox, le ':' dans la définition est manquant dans le composant '{component_name}' à la ligne : {opt_line.strip()}")
                equinox_parameter_name = parameter_name_and_default_value_math.group("equinox_parameter_name")
                component_parameter_name = parameter_name_and_default_value_math.group("component_parameter_name")
                equinox_component_parameter_value = parameter_name_and_default_value_math.group("equinox_component_parameter_value")
                equinox_component_parameter_value = equinox_component_parameter_value.strip()
                if equinox_component_parameter_value.startswith('<double-quote>'):
                    equinox_component_parameter_value = equinox_component_parameter_value[len('<double-quote>'):]
                if equinox_component_parameter_value.endswith('<double-quote>'):
                    equinox_component_parameter_value = equinox_component_parameter_value[:-len('<double-quote>')]
                equinox_component_parameter_value = equinox_component_parameter_value.replace("${", "$!{")
                equinox_component_parameter_value = equinox_component_parameter_value.replace('<double-quote>', '"')
                equinox_component_parameter_value = equinox_component_parameter_value.replace('<back-slash><back-slash>', '<double-back-slash>')
                equinox_component_parameter_value = equinox_component_parameter_value.replace('<back-slash>', '')
                equinox_component_parameter_value = equinox_component_parameter_value.replace('<double-back-slash>', '\\')
                if equinox_parameter_name is None or component_parameter_name is None or equinox_component_parameter_value is None:
                    print(f"     !! Vérifiez la liste des paramètres du composant dans equinox, impossible d'obtenir les informations par défaut dans le composant '{component_name}' à la ligne : {opt_line.strip()}")
                    continue
                if component_parameter_name not in equinox_parameter_value_by_component_parameter_name:
                    equinox_parameter_value_by_component_parameter_name[component_parameter_name] = equinox_component_parameter_value
                    equinox_parameter_name_by_component_parameter_name[component_parameter_name] = equinox_parameter_name
                else:
                    print(f"     !! Vérifiez la liste des paramètres du composant dans equinox, le paramètre '{component_parameter_name}' est défini plusieurs fois (par un nouveau paramètre equinox '{equinox_parameter_name}') dans le composant '{component_name}' à la ligne : {opt_line.strip()}")
                continue

            for component_parameter_name, equinox_parameter_name in equinox_parameter_name_by_component_parameter_name.items():
                pattern = f'OPT_{equinox_parameter_name}=["${{]*(?P<additional_equinox_parameter_value>[^ }}]*)'
                parameter_name_and_other_value_math = re.match(pattern, opt_line.strip())
                if parameter_name_and_other_value_math is None:
                    continue
                additional_equinox_parameter_value = parameter_name_and_other_value_math.group("additional_equinox_parameter_value").strip().strip('"')
                additional_equinox_parameter_value = additional_equinox_parameter_value.replace("${", "$!{")
                if additional_equinox_parameter_value is None:
                    print(f"     !! Vérifiez la liste des paramètres du composant dans equinox, impossible d'obtenir d'autres informations dans le composant '{component_name}' à la ligne : {opt_line.strip()}")
                    continue
                if "OPT_" in additional_equinox_parameter_value:
                    continue

                if component_parameter_name not in additional_equinox_parameter_by_component_parameter_name \
                        or additional_equinox_parameter_value not in additional_equinox_parameter_by_component_parameter_name[component_parameter_name]:
                    additional_equinox_parameter_by_component_parameter_name.setdefault(component_parameter_name, []).append(additional_equinox_parameter_value)

        return equinox_parameter_value_by_component_parameter_name, additional_equinox_parameter_by_component_parameter_name

    # noinspection GrazieInspection
    @staticmethod
    def _replace_references_on_evaluations_in_value(value: Union[str, int, float, bool, list, dict], safe_globals_dict: dict = None, safe_locals_dict: dict = None, max_number_of_loop=10) -> Optional[Union[str, int, float, bool, list, dict]]:
        """
        Évalue l'expression référencée par le motif '$<...>' et remplace le motif par le résultat de l'évaluation.
        En cas d'échec de l'évaluation, la fonction lève une exception UserWarning.
        La fonction effectue plusieurs boucles sur le résultat pour gérer les références imbriquées.
        """
        if not isinstance(value, str):
            return value

        if safe_globals_dict is None:
            safe_globals_dict = {}
        if safe_locals_dict is None:
            safe_locals_dict = {}

        output_value = value
        # make_final_evaluation = False
        loop_count = 0
        while loop_count < max_number_of_loop:
            loop_count += 1

            # noinspection RegExpRedundantEscape
            referenced_evaluations = re.findall(r"\$<((?:(?!\$<).)*?)>", output_value, re.MULTILINE)
            if len(referenced_evaluations) == 0:
                break

            for referenced_evaluation in referenced_evaluations:
                try:
                    safe_locals_dict_to_use = {}
                    safe_locals_dict_to_use.update(safe_locals_dict)

                    safe_global_dict_to_use = {
                        "__builtins__": {
                            "int": int,
                            "str": str,
                            "range": range,
                            "enumerate": enumerate,
                            "len": len,
                        }
                    }
                    safe_global_dict_to_use.update(safe_globals_dict)

                    eval_result = eval(referenced_evaluation, safe_global_dict_to_use, safe_locals_dict_to_use)
                except (NameError, TypeError, SyntaxError) as e:
                    raise UserWarning(f"L'évaluation de '''{referenced_evaluation}''' a échoué : {e}")
                else:
                    output_value = output_value.replace(f"$<{referenced_evaluation}>", str(eval_result))
                    # make_final_evaluation = True
        else:
            raise UserWarning(f"Le remplacement de l'évaluation n'a pas été effectué avant le nombre maximal de boucles autorisé")

        # if make_final_evaluation:
        #     try:
        #         final_eval_result = eval(output_value, {"__builtins__": None}, {})
        #     except (SyntaxError, NameError, TypeError):
        #         # Possiblement la chaîne à évaluer est une chaîne finale à cette étape
        #         pass
        #     else:
        #         output_value = final_eval_result

        return output_value

class DeploymentDescriptionDeployer(DeploymentDescriptionParser):
    # Nom du fichier JSON contenant la description du déploiement en cours
    runningDeploymentDescriptionJsonFileName = "running-deployment.json"
    # Clé indiquant le statut de déploiement en cours
    runningDeploymentStatusKey = "deploymentRunningStatus"
    # Clé indiquant si les composants GAN sont déployés
    isDeployedKey = "isDeployed"
    # Clé indiquant si les composants GAN sont en cours d'exécution
    isGanComponentsRunningKey = "isGanComponentsRunning"

    def __init__(self, deployment_folder_path: Path):
        DeploymentDescriptionParser.__init__(self)

        # Chemin vers le dossier de déploiement
        self.deploymentDirPath = deployment_folder_path
        # Chemin vers le fichier JSON de description du déploiement en cours
        self.runningDeploymentDescriptionJsonFile = self.deploymentDirPath / self.runningDeploymentDescriptionJsonFileName

    def _parse_the_deployment_description_json_file(self, deployment_description_json_file_path) -> NoReturn:
        # Analyse du fichier JSON de description du déploiement
        self._deployment_dict = self._get_dict_from_json_file(deployment_description_json_file_path)
        self.parse_deployment_description_dict(self._deployment_dict)

    def _process_key_starting(self, new_key_in_the_path: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> Optional[str]:
        key_dict_path = dict_path.get_the_path_to_a_following_step(new_key_in_the_path)
        parent_path_step = dict_path.get_the_last_step_of_the_path()

        if parent_path_step == self.key_words["label_of_a_node_dictionary"]:
            # Début du déploiement du nœud
            self._node_deployment_starting(key_dict_path, path_based_dict)

        if new_key_in_the_path.startswith(self.key_words["label_of_a_components_group"]):
            # Début du groupe de composants
            self._process_component_group_starting(key_dict_path, path_based_dict)
        elif parent_path_step == self.key_words["label_of_a_component_dictionary"]:
            # Début du déploiement du composant
            self._component_deployment_starting(key_dict_path, path_based_dict)

        return new_key_in_the_path

    def _process_key_ending(self, new_key_in_the_path: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        key_dict_path = dict_path.get_the_path_to_a_following_step(new_key_in_the_path)
        parent_path_step = dict_path.get_the_last_step_of_the_path()

        if parent_path_step == self.key_words["label_of_a_node_dictionary"]:
            # Fin du déploiement du nœud
            self._node_deployment_ending(key_dict_path, path_based_dict)

        if new_key_in_the_path.startswith(self.key_words["label_of_a_components_group"]):
            # Fin du groupe de composants
            self._component_group_deployment_ending(key_dict_path, path_based_dict)
        elif parent_path_step == self.key_words["label_of_a_component_dictionary"]:
            # Fin du déploiement du composant
            self._component_deployment_ending(key_dict_path, path_based_dict)

    def _process_final_value(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> bool:
        # Traitement de la valeur finale
        is_value_updated = False
        return is_value_updated

    def _node_deployment_starting(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        pass

    def _node_deployment_ending(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        pass

    def _process_component_group_starting(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        # Début du groupe de composants
        self._component_group_deployment_starting(dict_path, path_based_dict)

        component_group_dict = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path, default_value={})

        if self.key_words["label_of_a_database_dictionary"] in component_group_dict:
            # Déploiement de la base de données du groupe de composants
            self._component_group_database_deployment(dict_path.get_the_path_to_a_following_step(self.key_words["label_of_a_database_dictionary"]), path_based_dict)

    def _component_group_deployment_starting(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        pass

    def _component_group_deployment_ending(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        pass

    def _component_group_database_deployment(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        pass

    def _component_deployment_starting(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        pass

    def _component_deployment_ending(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        pass

    def _get_database_host_and_port_from_description_dict_path(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> Tuple[str, int]:
        # Récupération de l'hôte et du port de la base de données à partir du chemin d'accès du dictionnaire de description
        database_description_dict = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path)

        database_host = database_description_dict.get(self.key_words["label_of_the_database_host"], None)
        if database_host is None:
            raise UserWarning(f"La description de la base de données '{dict_path}' n'a pas défini son hôte de base de données")

        database_port = database_description_dict.get(self.key_words["label_of_the_database_port"], None)
        if database_port is None:
            raise UserWarning(f"La description de la base de données '{dict_path}' n'a pas défini son port de base de données")

        return database_host, database_port

    def _get_container_group(self, container_name: str) -> str:
        # Récupération du groupe de conteneurs
        return container_name.split("-")[1]

    def _get_from_here_to_the_top_of_the_dict_path_to_the_database_to_use(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> DictPath:
        _, _, database_to_use_dict_path = self._search_from_here_to_the_top_of_the_parameter_value(self.key_words["label_of_a_database_dictionary"], dict_path, path_based_dict)
        if database_to_use_dict_path is None:
            raise UserWarning(f"La base de données à utiliser à partir du chemin d'accès du dictionnaire '{dict_path}' n'est pas trouvée")
        return database_to_use_dict_path

    def _get_the_gan_project_name(self, path_based_dict: PathBasedDictionary) -> str:
        # Récupération du nom du projet GAN
        return path_based_dict.get_the_value_pointed_by_a_dict_path(DictPath(from_dict_path_as_list=[self.key_words["label_of_the_gan_project_name"]]))

    def _get_the_component_name_and_version(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> Tuple[str, str]:
        # Récupération du nom et de la version du composant
        components_version = path_based_dict.get_the_value_pointed_by_a_dict_path(DictPath(from_dict_path_as_list=[self.key_words["label_of_the_gan_version"]]))
        component_description_dict = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path)
        component_description_name = component_description_dict.get(self.key_words["label_of_the_component_description_name"], None)
        component_name = component_description_dict.get(self.key_words["label_of_the_component_name"], None)
        if component_name is None:
            raise UserWarning(f"Le groupe de composants '{dict_path}' n'a pas défini le nom du composant '{component_description_name}'")
        return component_name, components_version

    def _get_the_component_environments_variables(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> dict:
        # Récupération des variables d'environnement du composant
        component_description_dict = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path)
        component_environment_variables_by_name = component_description_dict.get(self.key_words["label_of_a_component_env_var_dictionary"], {})
        component_environment_variables_by_name = {k: json.dumps(v) if not isinstance(v, str) else v for k, v in component_environment_variables_by_name.items() if not k.startswith("DEFAULT VALUE OF")}
        return component_environment_variables_by_name

    def _get_the_component_environments_variables_for_subprocess(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> dict:
        # Récupération des variables d'environnement du composant pour un sous-processus
        component_environment_variables_by_name = self._get_the_component_environments_variables(dict_path, path_based_dict)

        os_env = copy.deepcopy(os.environ)
        env_to_use = dict(os_env)
        env_to_use.update(component_environment_variables_by_name)

        return env_to_use

    def is_gan_components_deployed(self) -> bool:
        # Vérifie si les composants GAN sont déployés
        return self._get_running_status_from_running_deployment_dict(self.isDeployedKey, default_value=False)

    def is_gan_components_running(self) -> bool:
        # Vérifie si les composants GAN sont en cours d'exécution
        return self._get_running_status_from_running_deployment_dict(self.isGanComponentsRunningKey, default_value=False)

    def _set_deployed_status(self, status_value: bool) -> NoReturn:
        # Définit le statut de déploiement
        self._set_running_status_to_running_deployment_dict(self.isDeployedKey, status_value)

    def _set_gan_components_running_status(self, status_value: bool) -> NoReturn:
        # Définit le statut d'exécution des composants GAN
        self._set_running_status_to_running_deployment_dict(self.isGanComponentsRunningKey, status_value)

    def _parse_the_running_deployment_dict(self) -> NoReturn:
        # Analyse du dictionnaire de déploiement en cours
        self._deployment_dict = self._get_dict_from_json_file(self.runningDeploymentDescriptionJsonFile)
        self.parse_deployment_description_dict(self._deployment_dict)

    def _read_the_running_deployment_dict(self) -> NoReturn:
        # Lecture du dictionnaire de déploiement en cours
        self._deployment_dict = self._get_dict_from_json_file(self.runningDeploymentDescriptionJsonFile)

    def _get_the_path_base_running_deployment_dict(self) -> NoReturn:
        # Récupération du chemin de base du dictionnaire de déploiement en cours
        self._read_the_running_deployment_dict()
        return PathBasedDictionary(self._deployment_dict)

    def _write_the_running_deployment_dict_to_json_file(self) -> NoReturn:
        # Écriture du dictionnaire de déploiement en cours dans un fichier JSON
        self._write_dict_to_json_file(self._deployment_dict, self.runningDeploymentDescriptionJsonFile)

    def _set_running_status_to_running_deployment_dict(self, running_status_name: str, running_status_value: Any) -> NoReturn:
        # Définit le statut de déploiement dans le dictionnaire de déploiement en cours
        self._deployment_dict.setdefault(self.runningDeploymentStatusKey, {})[running_status_name] = running_status_value
        self._write_the_running_deployment_dict_to_json_file()

    def _get_running_status_from_running_deployment_dict(self, running_status_name: str, default_value=None) -> Optional[Any]:
        # Récupère le statut de déploiement à partir du dictionnaire de déploiement en cours
        if self._deployment_dict is not None:
            return self._deployment_dict.get(self.runningDeploymentStatusKey, {}).get(running_status_name, default_value)

        if not self.runningDeploymentDescriptionJsonFile.exists():
            return default_value

        self._deployment_dict = self._get_dict_from_json_file(self.runningDeploymentDescriptionJsonFile)
        status_value = self._deployment_dict.get(self.runningDeploymentStatusKey, {}).get(running_status_name, default_value)
        self._deployment_dict = None

        return status_value
class PelDeploymentDescriptionParser(DeploymentDescriptionDeployer):
    # Nom du dossier PEL
    pelFolderName = "pel-target"
    # Nom du dossier racine de déploiement en cours
    runningDeploymentRootFolderName = "deployment"
    # Nom du dossier racine des bases de données en cours
    runningDeploymentDatabasesRootFolderName = "pg-data-root"
    # Nom du dossier racine des bases de données originales en cours
    runningDeploymentOriginalDatabasesRootFolderName = "pg-data-root-original"
    # Nom du dossier des journaux de déploiement en cours
    runningDeploymentLogFolderName = "logs"
    # PID de equinox-sh
    componentEquinoxShPid = "equinox-sh-pid"
    # Clé indiquant si le composant est en cours d'exécution
    isComponentRunning = "isComponentRunning"
    # Nom du fichier journal de launcher-sh
    launcherShLogFileName = "launcher-sh.log"
    # Nom du fichier journal de equinox-sh
    equinoxShLogFileName = "equinox-sh.log"
    # Nom du fichier journal de kill-equinox-sh
    killEquinoxShLogFileName = "kill-equinox-sh.log"
    # Clé indiquant si un DSL unique est déployé
    isSingleDslDeployedKey = "isSingleDslDeployed"
    # Clé indiquant si les bases de données sont en cours d'exécution
    isDatabasesRunningKey = "isDatabasesRunning"
    # Clé indiquant si les composants GAN d'un DSL unique sont en cours d'exécution
    isSingleDslGanComponentsRunningKey = "isSingleDslGanComponentsRunningKey"
    # Clé indiquant si un test est en cours
    isTestInProgressKey = "isTestInProgressKey"

    def __init__(self, deployment_folder_path: Path):
        # Chemin vers le dossier PEL
        self.pelDirPath = deployment_folder_path / self.pelFolderName

        DeploymentDescriptionDeployer.__init__(self, self.pelDirPath)

        # Chemin vers le dossier de déploiement en cours
        self.runningDeploymentPath = self.pelDirPath / self.runningDeploymentRootFolderName
        # Chemin vers le dossier des bases de données
        self.databasesDirPath = self.pelDirPath / self.runningDeploymentDatabasesRootFolderName
        # Chemin vers le dossier des bases de données originales
        self.originalDatabasesDirPath = self.pelDirPath / self.runningDeploymentOriginalDatabasesRootFolderName
        # Chemin vers le dossier des journaux
        self.logDirPath = self.pelDirPath / self.runningDeploymentLogFolderName

        self._deployment_dict = None

    def is_gan_components_single_dsl_deployed(self) -> bool:
        # Vérifie si les composants GAN d'un DSL unique sont déployés
        return self._get_running_status_from_running_deployment_dict(self.isSingleDslDeployedKey, default_value=False)

    def is_single_dsl_gan_components_running(self) -> bool:
        # Vérifie si les composants GAN d'un DSL unique sont en cours d'exécution
        return self._get_running_status_from_running_deployment_dict(self.isSingleDslGanComponentsRunningKey, default_value=False)

    def is_databases_running(self) -> bool:
        # Vérifie si les bases de données sont en cours d'exécution
        return self._get_running_status_from_running_deployment_dict(self.isDatabasesRunningKey, default_value=False)



class PelDeployer(PelDeploymentDescriptionParser):

    def __init__(self, deployment_folder_path: Path, component_config_dir_path: Path, component_tgz_dir_path: Path):
        PelDeploymentDescriptionParser.__init__(self, deployment_folder_path)

        # Chemin vers le dossier de configuration des composants
        self.componentConfigDirPath = component_config_dir_path
        # Chemin vers le dossier des fichiers tgz des composants
        self.componentTgzDirPath = component_tgz_dir_path

        self._removeStartAndDockerLoopFromEquinoxSh = None

    def deploy_from_deployment_description_json_file(self, deployment_description_json_file_path: Path, remove_start_and_docker_loop_from_equinox_sh: bool = False) -> NoReturn:
        # Déploie à partir d'un fichier JSON de description de déploiement
        if self.is_gan_components_running():
            raise UserWarning(f"Un déploiement est en cours dans le dossier '{self.pelDirPath}', arrêtez-le avant tout déploiement")

        self._removeStartAndDockerLoopFromEquinoxSh = remove_start_and_docker_loop_from_equinox_sh

        if self.pelDirPath.exists():
            print(f"     - Suppression de '{self.pelDirPath}'")
            shutil.rmtree(self.pelDirPath, ignore_errors=True)
        self.pelDirPath.mkdir(parents=True, exist_ok=True)

        if self.runningDeploymentPath.exists():
            print(f"     - Suppression de '{self.runningDeploymentPath}'")
            shutil.rmtree(self.runningDeploymentPath, ignore_errors=True)
        self.runningDeploymentPath.mkdir(parents=True, exist_ok=True)

        if self.logDirPath.exists():
            print(f"     - Suppression de '{self.logDirPath}'")
            shutil.rmtree(self.logDirPath, ignore_errors=True)
        self.logDirPath.mkdir(parents=True, exist_ok=True)

        self._parse_the_deployment_description_json_file(deployment_description_json_file_path)
        self._set_deployed_status(True)

    def _node_deployment_starting(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        # Démarre le déploiement d'un nœud
        node_name = dict_path.get_the_last_step_of_the_path()
        node_deployment_path = self.runningDeploymentPath.joinpath(*self._get_deployment_path(dict_path))

        print(f"     - Création du dossier '{node_name}' dans '{node_deployment_path.relative_to(self.deploymentDirPath)}'")
        if node_deployment_path.exists():
            shutil.rmtree(node_deployment_path, ignore_errors=True)
        node_deployment_path.mkdir(parents=True, exist_ok=True)

    def _component_group_deployment_starting(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        # Démarre le déploiement d'un groupe de composants
        component_group_deployment_name = "/".join(self._get_deployment_path(dict_path))
        component_group_deployment_path = self.runningDeploymentPath.joinpath(*self._get_deployment_path(dict_path))

        print(f"         - Effectuer un déploiement PEL du groupe de composants '{component_group_deployment_name}' dans le dossier '{component_group_deployment_path.relative_to(self.deploymentDirPath)}'")
        if component_group_deployment_path.exists():
            shutil.rmtree(component_group_deployment_path, ignore_errors=True)
        component_group_deployment_path.mkdir(parents=True, exist_ok=True)

    def _component_group_database_deployment(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        # Démarre le déploiement d'une base de données du groupe de composants
        database_dir_path, _, database_port = self._get_database_folder_path_host_and_port_from_description_dict_path(dict_path, path_based_dict)

        if not DataBase.create_database(database_dir_path):
            raise UserWarning(f"La création de la base de données '{database_dir_path.name}' a échoué")

        print(f"         - La création de la base de données '{database_dir_path.name}' est terminée")

        if not DataBase.start_database(database_dir_path, database_port):
            raise UserWarning(f"Le démarrage de la base de données '{database_dir_path.name}' sur le port '{database_port}' a échoué")

        print(f"         - La base de données '{database_dir_path.name}' sur le port '{database_port}' est démarrée")

        self._set_databases_running_status(True)

    def _component_deployment_starting(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        # Démarre le déploiement d'un composant
        component_deployment_name, component_deployment_path = self._get_the_component_deployment_name_and_path(dict_path)
        subprocess_environment_variables = self._get_the_component_environments_variables_for_subprocess(dict_path, path_based_dict)
        component_name, components_version = self._get_the_component_name_and_version(dict_path, path_based_dict)
        gen_project_name = self._get_the_gan_project_name(path_based_dict)

        print(f"             - Création du composant '{component_deployment_name}' dans le dossier '{component_deployment_path.relative_to(self.deploymentDirPath)}'")
        component_tgz_name = self._get_component_associated_tgz_name(component_name, components_version, gen_project_name)
        print(f"                 - Décompression du fichier tgz associé au composant '{component_tgz_name}'")
        tgz_file_path = self.componentTgzDirPath / component_tgz_name
        if not tgz_file_path.exists() or not tarfile.is_tarfile(tgz_file_path):
            raise UserWarning(f"Le fichier tgz du composant '{tgz_file_path.relative_to(self.componentTgzDirPath)}' n'existe pas ou n'est pas un fichier tar")
        try:
            with tarfile.open(tgz_file_path, "r:gz") as tar:
                tar.extractall(component_deployment_path)
        except (OSError, tarfile.TarError) as e:
            raise UserWarning(f"Échec de l'extraction du fichier tgz '{tgz_file_path.relative_to(self.componentTgzDirPath)}': {e}")

        component_equinox_source_file_path = self.componentConfigDirPath / component_name / "equinox.sh"
        component_equinox_destination_file_path = component_deployment_path / "equinox.sh"

        if self._removeStartAndDockerLoopFromEquinoxSh:
            print(f"                 - Copie d'une version tronquée du fichier de script associé au composant '{component_equinox_source_file_path.relative_to(self.componentConfigDirPath)}'")
            sh_file_lines = []
            try:
                with component_equinox_source_file_path.open("r") as sh_file:
                    for line in sh_file.readlines():
                        if not line.lstrip().startswith("./launcher.sh start"):
                            sh_file_lines.append(line)
                        else:
                            break
            except OSError as e:
                raise UserWarning(f"Échec de chargement du contenu du fichier '{component_equinox_source_file_path.relative_to(self.componentConfigDirPath)}': {e}")

            try:
                with component_equinox_destination_file_path.open("w", newline="\n") as sh_file:
                    sh_file.writelines(sh_file_lines)
                # Restauration des autorisations du fichier
                os.chmod(component_equinox_destination_file_path, 0o777)
            except OSError as e:
                raise UserWarning(f"Échec de l'écriture du contenu du fichier '{component_equinox_destination_file_path.relative_to(self.deploymentDirPath)}': {e}")
        else:
            print(f"                 - Copie du fichier de script associé au composant '{component_equinox_source_file_path.relative_to(self.componentConfigDirPath)}'")
            shutil.copy2(str(component_equinox_source_file_path), str(component_equinox_destination_file_path))

        print(f"                 - Exécution du fichier de script '{component_equinox_destination_file_path.relative_to(self.deploymentDirPath)}'")
        command_arguments = ["./" + component_equinox_destination_file_path.name]
        command_arguments = adapt_the_command_arguments_when_using_bash_on_windows(command_arguments)

        log_file_path = self._get_the_component_log_file_path(dict_path) / self.equinoxShLogFileName
        log_file_path.parent.mkdir(parents=True, exist_ok=True)

        if self._removeStartAndDockerLoopFromEquinoxSh:
            run_subprocess(log_file_path, command_arguments,
                           environment_variables=subprocess_environment_variables,
                           current_working_directory=component_equinox_destination_file_path.parent)
        else:
            self._set_gan_components_running_status(True)

            print(f"                     - Détacher le processus...")
            process = run_detach_subprocess(log_file_path, command_arguments, environment_variables=subprocess_environment_variables, current_working_directory=component_equinox_destination_file_path.parent)

            print(f"                     - ID du processus détaché : {process.pid}")
            path_based_dict.set_the_value_pointed_by_a_dict_path(process.pid, dict_path.get_the_path_to_a_following_step(self.componentEquinoxShPid))

            path_based_dict.set_the_value_pointed_by_a_dict_path(True, dict_path.get_the_path_to_a_following_step(self.isComponentRunning))

    @staticmethod
    def _get_component_associated_tgz_name(component_name: str, gan_version: str, gan_project_name) -> str:
        # Retourne le nom du fichier tgz associé au composant
        return f"{gan_project_name}-{gan_version}-{component_name}.tar.gz"

class PelRunning(PelDeploymentDescriptionParser):

    def __init__(self, deployment_folder_path: Path):
        # Initialise la classe PelRunning
        PelDeploymentDescriptionParser.__init__(self, deployment_folder_path)
        self._singleDslPel = SingleDslPel(deployment_folder_path)
        self._actionToBePerformed = None
        self._runningComponentsCount = None

    def start(self, component_deployment_path: str = None) -> NoReturn:
        # Démarre les composants Gan
        if not self.is_gan_components_deployed():
            print(" - Les composants Gan ne sont pas déployés")
            return

        if component_deployment_path is not None:
            if self.is_single_dsl_gan_components_running():
                print(" - Non disponible pendant qu'un déploiement DSL unique est en cours")
            else:
                self._perform_the_action_on_one_component(component_deployment_path, "start")
                self._set_gan_components_running_status(True)
        else:
            if self.is_databases_running():
                print(" - Les bases de données sont déjà en cours d'exécution")
            else:
                self._perform_the_action("start-databases")

                print(" - Pause pendant 30 secondes pour permettre le démarrage des bases de données...")
                time.sleep(30)

            if self.is_gan_components_running():
                print(" - Les composants Gan sont déjà en cours d'exécution")
            else:
                if self.logDirPath.exists():
                    shutil.rmtree(self.logDirPath, ignore_errors=True)
                self.logDirPath.mkdir(parents=True, exist_ok=True)

                self._perform_the_action("start")
                self._set_gan_components_running_status(True)

    def stop(self, component_deployment_path: str = None) -> NoReturn:
        # Arrête les composants Gan
        if self.is_single_dsl_gan_components_running():
            print(" - Non disponible pendant qu'un déploiement DSL unique est en cours")
            return

        if component_deployment_path is not None:
            self._perform_the_action_on_one_component(component_deployment_path, "stop")

            if self._count_the_running_components() == 0:
                self._set_gan_components_running_status(False)
        else:
            if self.is_databases_running():
                self._perform_the_action("stop-databases")
                self._set_databases_running_status(False)
            else:
                print(" - Aucune base de données à arrêter")

            if not self.is_gan_components_running():
                print(" - Aucun composant Gan à arrêter")
            else:
                self._perform_the_action("stop")
                self._set_gan_components_running_status(False)

    def _count_the_running_components(self) -> int:
        # Compte les composants en cours d'exécution
        self._runningComponentsCount = 0
        self._actionToBePerformed = "countRunning"
        self._parse_the_running_deployment_dict()
        return self._runningComponentsCount

    def _get_components_path_in_description_order(self) -> List[Path]:
        # Récupère les chemins des composants dans l'ordre de description
        self._componentsPathInDescriptionOrder = []
        self._actionToBePerformed = "getComponentsPath"
        self._parse_the_running_deployment_dict()
        return self._componentsPathInDescriptionOrder

    def _perform_the_action(self, action: str) -> NoReturn:
        # Exécute l'action spécifiée sur tous les composants
        self._actionToBePerformed = action

        self._parse_the_running_deployment_dict()
        self._write_the_running_deployment_dict_to_json_file()

    def _perform_the_action_on_one_component(self, component_deployment_path: str, action: str) -> NoReturn:
        # Exécute l'action spécifiée sur un composant
        self._actionToBePerformed = action

        if not self.logDirPath.exists():
            self.logDirPath.mkdir(parents=True, exist_ok=True)

        path_base_dict = self._get_the_path_base_running_deployment_dict()
        _, _, dict_path = self._search_by_deployment_path(component_deployment_path, DictPath(), path_base_dict)
        if dict_path is None:
            print(f" ! L'action '{action}' sur le composant '{component_deployment_path}' a échoué, le chemin cible n'est pas trouvé")
            return

        if dict_path.get_the_path_to_parent().get_the_last_step_of_the_path() != self.key_words["label_of_a_component_dictionary"]:
            print(f" ! L'action '{action}' sur le composant '{component_deployment_path}' a échoué, le chemin cible n'est pas un composant")
            return

        self._component_deployment_starting(dict_path, path_base_dict)
        self._write_the_running_deployment_dict_to_json_file()

    def _component_group_database_deployment(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        # Déploie ou arrête les bases de données du groupe de composants
        if self._actionToBePerformed == "start-databases":
            database_dir_path, _, database_port = self._get_database_folder_path_host_and_port_from_description_dict_path(dict_path, path_based_dict)

            if not DataBase.start_database(database_dir_path, database_port):
                print(f"     - Le démarrage de la base de données '{database_dir_path.name}' a échoué")
            else:
                print(f"     - La base de données '{database_dir_path.name}' est démarrée")

            self._set_databases_running_status(True)
        elif self._actionToBePerformed == "stop-databases":
            database_dir_path, _, database_port = self._get_database_folder_path_host_and_port_from_description_dict_path(dict_path, path_based_dict)

            if not DataBase.stop_database(database_dir_path):
                print(f"     - L'arrêt de la base de données '{database_dir_path.name}' a échoué")
            else:
                print(f"     - La base de données '{database_dir_path.name}' est arrêtée")

    # noinspection PyUnusedLocal
    def _component_deployment_starting(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        # Démarre ou arrête le déploiement d'un composant
        if self._actionToBePerformed not in ("start", "stop", "countRunning", "getComponentsPath"):
            return

        component_deployment_name, component_deployment_path = self._get_the_component_deployment_name_and_path(dict_path)
        subprocess_environment_variables = self._get_the_component_environments_variables_for_subprocess(dict_path, path_based_dict)

        is_component_running_dict_path = dict_path.get_the_path_to_a_following_step(self.isComponentRunning)
        is_component_running = path_based_dict.get_the_value_pointed_by_a_dict_path(is_component_running_dict_path, default_value=False)

        if self._actionToBePerformed == "countRunning":
            if is_component_running:
                self._runningComponentsCount += 1
            return

        if is_component_running and self._actionToBePerformed == "start":
            print(f"     - Le composant '{component_deployment_name}' est déjà démarré")
            return

        if not is_component_running and self._actionToBePerformed == "stop":
            print(f"     - Le composant '{component_deployment_name}' est déjà arrêté")
            return

        component_equinox_sh_pid_dict_path = dict_path.get_the_path_to_a_following_step(self.componentEquinoxShPid)
        component_equinox_sh_pid = path_based_dict.get_the_value_pointed_by_a_dict_path(component_equinox_sh_pid_dict_path, default_value=None)
        component_launcher_file_path = component_deployment_path / "launcher.sh"

        if self._actionToBePerformed == "getComponentsPath":
            self._componentsPathInDescriptionOrder.append(component_deployment_path)
            return

        print(f"     - {self._actionToBePerformed.capitalize()} le composant '{component_deployment_name}', donc exécuter ce fichier de script '{component_launcher_file_path.name} {self._actionToBePerformed}'")
        command_arguments = ["./" + component_launcher_file_path.name, self._actionToBePerformed]
        command_arguments = adapt_the_command_arguments_when_using_bash_on_windows(command_arguments)

        log_file_path = self._get_the_component_log_file_path(dict_path) / f"{self._actionToBePerformed}-{self.launcherShLogFileName}"
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        complete_process = run_subprocess(log_file_path, command_arguments, environment_variables=subprocess_environment_variables, current_working_directory=component_launcher_file_path.parent)
        if complete_process.returncode != 0:
            print(f"        ! L'action '{self._actionToBePerformed.capitalize()}' sur le composant '{component_deployment_name}' a échoué")
        else:
            path_based_dict.set_the_value_pointed_by_a_dict_path(self._actionToBePerformed == "start", dict_path.get_the_path_to_a_following_step(self.isComponentRunning))

        if self._actionToBePerformed == "stop":
            if component_equinox_sh_pid is not None:
                print(f"     - Arrêter le processus equinox.sh du composant '{dict_path}' pid {component_equinox_sh_pid}")
                if platform.system() == "Windows":
                    # # os.kill(component_equinox_sh_pid, signal.SIGTERM)
                    log_file_path = self._get_the_component_log_file_path(dict_path) / self.killEquinoxShLogFileName
                    log_file_path.parent.mkdir(parents=True, exist_ok=True)
                    run_subprocess(log_file_path, ['taskkill', '/F', '/T', '/PID', str(component_equinox_sh_pid)])
                else:
                    os.kill(component_equinox_sh_pid, signal.SIGTERM)
                path_based_dict.delete_the_last_key_given_by_a_dict_path(component_equinox_sh_pid_dict_path)

            if (component_deployment_path / "logs").exists():
                log_file_dir_path = self._get_the_component_log_file_path(dict_path)
                log_file_dir_path.parent.mkdir(parents=True, exist_ok=True)
                print(f"     - Copier les journaux du composant '{component_deployment_name}' vers '{log_file_dir_path.relative_to(self.logDirPath)}'")
                copy_tree(str(component_deployment_path / "logs"), str(log_file_dir_path), preserve_mode=True)

    def build_single_dsl_pel(self, dsl_log_xml_trace_level: str = "DEBUG", dsl_log_xml_max_log_file_size: int = 10240000):
        # Construit un PEL DSL unique
        if not self.is_gan_components_deployed():
            print(" - Les composants Gan ne sont pas déployés")
            return

        if self.is_gan_components_running():
            print(" - Les composants Gan sont en cours d'exécution, arrêtez-les avant de tenter de construire un PEL DSL unique")
            return

        ordered_dsl_paths = self._get_components_path_in_description_order()

        self._read_the_running_deployment_dict()
        self._singleDslPel.build_single_dsl_pel_deployment(dsl_log_xml_trace_level, dsl_log_xml_max_log_file_size, ordered_dsl_paths)
        self._set_single_dsl_deployed_status(True)

    def start_single_dsl_pel(self):
        # Démarre un PEL DSL unique
        if not self.is_gan_components_single_dsl_deployed():
            print(" - Les composants Gan ne sont pas déployés en tant que PEL DSL unique")
            return

        if self.is_databases_running():
            print(" - Les bases de données sont déjà en cours d'exécution")
        else:
            self._perform_the_action("start-databases")

            print(" - Pause pendant 30s pour permettre le démarrage des bases de données...")
            time.sleep(30)

        if self.is_gan_components_running():
            print(" - Les composants Gan sont déjà en cours d'exécution")
        else:
            self._read_the_running_deployment_dict()
            self._singleDslPel.start_single_dsl()
            self._set_gan_components_running_status(True)
            self._set_single_dsl_gan_components_running_status(True)

    def stop_single_dsl_pel(self):
        # Arrête un PEL DSL unique
        if not self.is_single_dsl_gan_components_running():
            print(" - Non disponible tant qu'aucun déploiement PEL DSL unique n'est en cours")
            return

        if self.is_databases_running():
            self._perform_the_action("stop-databases")
            self._set_databases_running_status(False)
        else:
            print(" - Aucune base de données à arrêter")

        if not self.is_gan_components_running():
            print(" - Aucun composant Gan à arrêter")
        else:
            self._read_the_running_deployment_dict()
            self._singleDslPel.stop_single_dsl()
            self._set_gan_components_running_status(False)
            self._set_single_dsl_gan_components_running_status(False)

    def copy_working_databases_data_root_folder_as_original(self) -> NoReturn:
        # Copie le dossier racine des données des bases de données en tant qu'original
        if self.is_databases_running():
            print("Les bases de données fonctionnent, donc impossible de faire la copie originale")
            return

        if not DataBase.save_databases_data_folders(self.databasesDirPath, self.originalDatabasesDirPath):
            print(f"La copie des dossiers de données des bases de données en cours a échoué")
        else:
            print(f"Les dossiers de données des bases de données en cours sont enregistrés en tant qu'originaux")

    def restore_working_databases_data_root_folder_from_original(self) -> NoReturn:
        # Restaure le dossier racine des données des bases de données à partir de l'original
        if self.is_databases_running():
            print("Les bases de données fonctionnent, donc impossible de restaurer l'original")
            return

        if not DataBase.restore_databases_data_folders(self.originalDatabasesDirPath, self.databasesDirPath):
            print(f"La restauration des dossiers de données des bases de données en cours a échoué")
        else:
            print(f"Les dossiers de données des bases de données en cours sont restaurés")

    def test(self, cataclysm_folder_path: Path, test_profile: str, test_name_to_run: str = None) -> NoReturn:
        # Exécute les tests
        if not self.is_databases_running():
            print(" - Les bases de données ne sont pas en cours d'exécution")
            return

        if not self.is_gan_components_running():
            print(" - Les composants Gan ne sont pas en cours d'exécution")
            return

        print(f" - Tester le déploiement dans le dossier '{self.runningDeploymentPath}'")

        self._read_the_running_deployment_dict()
        self._set_test_in_progress_status(True)

        working_repository = None

        command_arguments = [
            "mvn", "clean", "install",
            f"-P{test_profile}",
            "-fae",
            "-Dmaven.test.failure.ignore=false",
        ]

        if working_repository is not None:
            command_arguments.append(f"-Dmaven.repo.local=\"{working_repository}\"")

        mvn_options_associated_to_deployment_dict = self._deployment_dict.get(self.key_words["label_of_a_pel_section"], {}).get("mvnOptionsAssociatedToDeployment", {})
        for option_name, option_value in mvn_options_associated_to_deployment_dict.items():
            command_arguments.append(f"{option_name}={option_value}")

        if test_name_to_run is not None:
            command_arguments.append(f"-Dtest={test_name_to_run}")

        command_arguments = adapt_the_command_arguments_when_using_bash_on_windows(command_arguments)

        if not self.is_single_dsl_gan_components_running():
            log_file_path = self.logDirPath / "test.log"
        else:
            log_file_path = self.logDirPath / "single-dsl-test.log"

        print(command_arguments)
        run_subprocess(log_file_path, command_arguments, current_working_directory=cataclysm_folder_path)

        self._set_test_in_progress_status(False)

class DataBase:

    @staticmethod
    def create_database(database_data_dir_path: Path) -> bool:
        # Crée une base de données
        print(f"    - Créer une base de données dans le dossier '{database_data_dir_path}'...")

        print(f"        - Supprimer si existant et créer le dossier de base de données '{database_data_dir_path}'...")
        if database_data_dir_path.exists():
            shutil.rmtree(database_data_dir_path, ignore_errors=True)
        database_data_dir_path.mkdir(parents=True, exist_ok=True)

        if platform.system() != "Windows" and os.geteuid() == 0:
            complete_process = subprocess.run(["chown", "postgres:postgres", "-R", str(database_data_dir_path)],
                                              cwd=None, text=True, capture_output=True)
            if complete_process.returncode != 0:
                print(f"Échec de la définition du propriétaire 'postgres:postgres' du dossier'{database_data_dir_path}'")
                return False
            else:
                print(f"Définition du propriétaire 'postgres:postgres' du dossier'{database_data_dir_path}' réussie")

        print(f"        - Initialiser la base de données PostgreSQL dans le dossier '{database_data_dir_path}'...")
        command_arguments = [
            "initdb",
            "--pgdata",
            f"{database_data_dir_path}",
            "-U", "postgres",
        ]

        log_file_path = database_data_dir_path.parent / f"{database_data_dir_path.name}-creation.log"
        log_file_path.parent.mkdir(parents=True, exist_ok=True)

        if platform.system() != "Windows" and os.geteuid() == 0:
            subprocess_kwargs = {"user": "postgres"}
        else:
            subprocess_kwargs = {}
        complete_process = run_subprocess(log_file_path, command_arguments, **subprocess_kwargs)

        if complete_process.returncode != 0:
            print(f"    ! L'initialisation de la base de données dans le dossier '{database_data_dir_path}' a échoué, code de retour {complete_process.returncode}: {complete_process.stderr} - {complete_process.stdout}")
            return False

        print(f"        - Mettre à jour 'pg_hba.conf'...")
        pg_hba_conf_file_path = database_data_dir_path / "pg_hba.conf"

        shutil.copy2(str(pg_hba_conf_file_path), str(pg_hba_conf_file_path) + ".backup")

        is_ipv4_local_connections_line = False
        is_ipv6_local_connections_line = False

        try:
            with pg_hba_conf_file_path.open("r") as psql_cfg_file:
                pg_hba_conf_file_lines = psql_cfg_file.readlines()
        except OSError as e:
            raise UserWarning(f"Échec de la lecture du contenu du fichier '{pg_hba_conf_file_path}': {e}")

        new_pg_hba_conf_file_lines = []
        for line in pg_hba_conf_file_lines:
            line = line.rstrip("\n")
            line = line.rstrip("\r")
            if is_ipv4_local_connections_line:
                new_pg_hba_conf_file_lines.append("host    all             all             all                     trust\n")
                is_ipv4_local_connections_line = False
                continue
            elif is_ipv6_local_connections_line:
                new_pg_hba_conf_file_lines.append("host    all             all             all                     trust\n")
                is_ipv6_local_connections_line = False
                continue
            elif line.startswith("# IPv4 local connections:"):
                is_ipv4_local_connections_line = True
            elif line.startswith("# IPv6 local connections:"):
                is_ipv6_local_connections_line = True
            new_pg_hba_conf_file_lines.append(line + "\n")

        try:
            with pg_hba_conf_file_path.open("w", newline="\n") as psql_cfg_file:
                psql_cfg_file.writelines(new_pg_hba_conf_file_lines)
        except OSError as e:
            raise UserWarning(f"Échec de l'écriture du contenu du fichier '{pg_hba_conf_file_path}': {e}")

        print(f"        - Mettre à jour 'postgresql.conf' pour le système '{platform.system()}'...")
        postgresql_conf_file_path = database_data_dir_path / "postgresql.conf"

        shutil.copy2(str(postgresql_conf_file_path), str(postgresql_conf_file_path) + ".backup")

        is_windows = (platform.system() == "Windows")

        try:
            with postgresql_conf_file_path.open("r") as psql_cfg_file:
                postgres_conf_file_lines = psql_cfg_file.readlines()
        except OSError as e:
            raise UserWarning(f"Échec de la lecture du contenu du fichier '{postgresql_conf_file_path}': {e}")

        new_postgres_conf_file_lines = []
        for line in postgres_conf_file_lines:
            line = line.rstrip("\n")
            line = line.rstrip("\r")
            if line.startswith("#listen_addresses = 'localhost'"):
                new_postgres_conf_file_lines.append("listen_addresses = '*'			# what IP address(es) to listen on;\n")
                continue
            if is_windows and line.startswith("dynamic_shared_memory_type = posix"):
                new_postgres_conf_file_lines.append("dynamic_shared_memory_type = windows	# the default is the first option\n")
                continue
            if not is_windows and line.startswith("dynamic_shared_memory_type = windows"):
                new_postgres_conf_file_lines.append("dynamic_shared_memory_type = posix	# the default is the first option\n")
                continue
            new_postgres_conf_file_lines.append(line + "\n")

        try:
            with postgresql_conf_file_path.open("w", newline="\n") as psql_cfg_file:
                psql_cfg_file.writelines(new_postgres_conf_file_lines)
        except OSError as e:
            raise UserWarning(f"Échec de l'écriture du contenu du fichier '{postgresql_conf_file_path}': {e}")

        print(f"        - Création de la base de données dans le dossier '{database_data_dir_path}' terminée")
        return True

    @staticmethod
    def start_database(database_data_dir_path: Path, database_port: int) -> bool:
        # Démarre la base de données
        print(f"Tentative de démarrage de la base de données sur le port {database_port} et dans le dossier de données'{database_data_dir_path}'...")
        database_log_file_path = database_data_dir_path.parent / f"{database_data_dir_path.name}.log"
        option_string = f"-F -p {database_port}"
        command_arguments = [
            "pg_ctl", "-s", "-w",
            "-D", f"{database_data_dir_path}",
            "-l", f"{database_log_file_path}",
            "-o", option_string,
            "-U", "postgres",
            "start"
        ]
        if platform.system() != "Windows" and os.geteuid() == 0:
            complete_process = subprocess.run(command_arguments, user="postgres")
        else:
            complete_process = subprocess.run(command_arguments)
        if complete_process.returncode != 0:
            print(f"Échec du démarrage de la base de données sur le port {database_port} et dans le dossier de données'{database_data_dir_path}'")
            return False
        else:
            print(f"Démarrage de la base de données sur le port {database_port} et dans le dossier de données'{database_data_dir_path}' réussi")

        return True

    @staticmethod
    def stop_database(database_data_dir_path: Path) -> bool:
        # Arrête la base de données
        print(f"Tentative d'arrêt de la base de données dans le dossier de données'{database_data_dir_path}'...")
        command_arguments = ["pg_ctl", "-s", "-w", "-D", f"{database_data_dir_path}", "stop"]
        if platform.system() != "Windows" and os.geteuid() == 0:
            complete_process = subprocess.run(command_arguments, user="postgres", cwd=None, text=True, capture_output=True)
        else:
            complete_process = subprocess.run(command_arguments, cwd=None, text=True, capture_output=True)
        if complete_process.returncode != 0:
            print(f"Échec de l'arrêt de la base de données dans le dossier de données'{database_data_dir_path}': {complete_process.stderr} - {complete_process.stdout}")
            return False
        else:
            print(f"Arrêt de la base de données dans le dossier de données'{database_data_dir_path}' réussi")
        return True

    @staticmethod
    def save_databases_data_folders(databases_working_root_dir_path: Path, databases_original_root_dir_path: Path) -> bool:
        # Sauvegarde les dossiers de données des bases de données
        if not databases_working_root_dir_path.exists():
            print(f"Le dossier de travail '{databases_working_root_dir_path}' n'existe pas")
            return False

        if databases_original_root_dir_path.exists():
            print(f"Supprimer l'existant '{databases_original_root_dir_path}'")
            shutil.rmtree(databases_original_root_dir_path, ignore_errors=True)

        print(f"Copier le dossier de travail '{databases_working_root_dir_path}' vers '{databases_original_root_dir_path}'")
        shutil.copytree(str(databases_working_root_dir_path), str(databases_original_root_dir_path))

        return True

    @staticmethod
    def restore_databases_data_folders(databases_original_root_dir_path: Path, databases_working_root_dir_path: Path) -> bool:
        # Restaure les dossiers de données des bases de données
        print(f"Initialiser le dossier de données des bases de données '{databases_working_root_dir_path}'...")

        if not databases_original_root_dir_path.exists():
            print(f"Le dossier d'origine '{databases_original_root_dir_path}' n'existe pas")
            return False

        if databases_working_root_dir_path.exists():
            print(f"Supprimer l'existant '{databases_working_root_dir_path}'")
            shutil.rmtree(databases_working_root_dir_path, ignore_errors=True)

        print(f"Copier le dossier d'origine '{databases_original_root_dir_path}' vers '{databases_working_root_dir_path}'")
        shutil.copytree(str(databases_original_root_dir_path), str(databases_working_root_dir_path))

        if platform.system() != "Windows" and os.geteuid() == 0:
            print(f"Tentative de définir les autorisations '0700' pour le dossier '{databases_working_root_dir_path}'...")
            complete_process = subprocess.run(["chmod", "0700", "-R", str(databases_working_root_dir_path)], cwd=None,
                                              text=True, capture_output=True)
            if complete_process.returncode != 0:
                print(f"Échec de la définition des autorisations '0700' pour le dossier '{databases_working_root_dir_path}'")
                return False
            else:
                print(f"Définition des autorisations '0700' pour le dossier '{databases_working_root_dir_path}' réussie")

            print(f"Tentative de définir le propriétaire 'postgres:postgres' pour le dossier '{databases_working_root_dir_path}'...")
            complete_process = subprocess.run(["chown", "postgres:postgres", "-R", str(databases_working_root_dir_path)],
                                              cwd=None, text=True, capture_output=True)
            if complete_process.returncode != 0:
                print(f"Échec de la définition du propriétaire 'postgres:postgres' pour le dossier '{databases_working_root_dir_path}'")
                return False
            else:
                print(f"Définition du propriétaire 'postgres:postgres' pour le dossier '{databases_working_root_dir_path}' réussie")

        print(f"Le dossier de données des bases de données '{databases_working_root_dir_path}' est initialisé")
        return True
class SingleDslPel:
    # Noms des dossiers et fichiers utilisés pour le déploiement du PEL DSL unique
    singleDslPelDeploymentRootFolderName = "single-dsl-pel-deployment"
    consoleSingleDslLogFileName = "single-dsl-console.log"
    singleDslLogFolderName = "single-dsl-logs"

    def __init__(self, deployment_folder_path: Path):
        # Chemins vers les dossiers et fichiers nécessaires pour le déploiement
        self.allDslRootDirPath = deployment_folder_path / PelDeploymentDescriptionParser.pelFolderName / PelDeploymentDescriptionParser.runningDeploymentRootFolderName
        self.singleDslTargetDirPath = deployment_folder_path / PelDeploymentDescriptionParser.pelFolderName / self.singleDslPelDeploymentRootFolderName
        self.logDirPath = deployment_folder_path / PelDeploymentDescriptionParser.pelFolderName / PelDeploymentDescriptionParser.runningDeploymentLogFolderName
        self.singleDslLogFolderPath = self.logDirPath / self.singleDslLogFolderName

    # Méthode pour construire le déploiement PEL DSL unique
    def build_single_dsl_pel_deployment(self, dsl_log_xml_trace_level: str = "DEBUG", dsl_log_xml_max_log_file_size: int = 10240000,
                                        ordered_dsl_paths: List[Path] = None) -> bool:
        # Vérifier si le dossier de déploiement PEL existe
        if not self.allDslRootDirPath.is_dir():
            raise UserWarning(f"Le dossier de déploiement PEL '{self.allDslRootDirPath}' n'existe pas!")

        # Supprimer le dossier cible s'il existe déjà
        if self.singleDslTargetDirPath.exists():
            print(f"Suppression de '{self.singleDslTargetDirPath}' existant")
            shutil.rmtree(self.singleDslTargetDirPath, ignore_errors=True)
        self.singleDslTargetDirPath.mkdir(parents=True, exist_ok=True)

        self.logDirPath.mkdir(parents=True, exist_ok=True)

        # Obtenir les chemins des DSLs dans l'ordre si spécifié
        if ordered_dsl_paths is None:
            dsl_paths = self.list_the_dsl_in_folder()
        else:
            dsl_paths = ordered_dsl_paths

        # Fusionner les fichiers JAR des dossiers DSL "bin" en un seul dossier
        self._merge_the_jar_files_from_dsl_folders_into_one_folder("bin", dsl_paths)

        # Fusionner les fichiers JAR des dossiers DSL "lib" en un seul dossier
        self._merge_the_jar_files_from_dsl_folders_into_one_folder("lib", dsl_paths)

        # Fusionner les fichiers de ressources des dossiers DSL "resources" en un seul dossier
        self._merge_the_resources_files_from_dsl_folders_into_one_folder("resources", dsl_paths)

        # Fusionner les fichiers autres que les fichiers de définition DSL des dossiers DSL "etc" en un seul dossier
        self._merge_the_files_other_than_the_dsl_definition_files_from_dsl_folders_into_one_folder(["dsl.json", self.consoleSingleDslLogFileName], "etc", dsl_paths)

        # Fusionner les fichiers "dsl.json" des dossiers DSL "etc" en un seul fichier
        single_dsl_json_file_path, special_dsl_json_file_path_list = self._merge_the_dsl_json_file_from_dsl_folders_into_one_file("dsl.json", "etc", dsl_paths)
        if single_dsl_json_file_path is None:
            print("ERREUR: Impossible de créer le fichier JSON DSL, abandon!")
            return False

        # Construire le fichier "dsl.log4j.xml" du DSL unique à partir du fichier "dsl.json" unique
        if not self._build_the_single_dsl_log_xml_file_from_the_single_dsl_json_file(self.consoleSingleDslLogFileName, single_dsl_json_file_path,
                                                                                     trace_level=dsl_log_xml_trace_level,
                                                                                     max_log_file_size=dsl_log_xml_max_log_file_size):
            print("ERREUR: Impossible de construire le fichier log4j.xml du DSL, abandon!")
            return False

        # Pour chaque DSL spécial, construire le fichier "dsl.log4j.xml" et copier les dossiers
        for special_dsl_json_file_path in special_dsl_json_file_path_list:
            if not self._build_the_single_dsl_log_xml_file_from_the_single_dsl_json_file(self.consoleSingleDslLogFileName, special_dsl_json_file_path,
                                                                                         trace_level=dsl_log_xml_trace_level,
                                                                                         max_log_file_size=dsl_log_xml_max_log_file_size):
                print("ERREUR: Impossible de construire le fichier log4j.xml du DSL, abandon!")
                return False

            single_dsl_folder_path = single_dsl_json_file_path.parent.parent
            special_dsl_folder_path = special_dsl_json_file_path.parent.parent
            shutil.copytree(str(single_dsl_folder_path / "bin"), str(special_dsl_folder_path / "bin"))
            shutil.copytree(str(single_dsl_folder_path / "lib"), str(special_dsl_folder_path / "lib"))
            shutil.copytree(str(single_dsl_folder_path / "resources"), str(special_dsl_folder_path / "resources"))

        return True

    # Méthode pour démarrer le DSL unique
    def start_single_dsl(self) -> bool:
        if not self.start_dsl(self.singleDslTargetDirPath / "main-dsl-folder"):
            return True

        has_some_failures = False
        single_dsl_folders = self.singleDslTargetDirPath.glob("*dsl-folder*")
        for single_dsl_folder in single_dsl_folders:
            if single_dsl_folder.name == "main-dsl-folder":
                continue

            if not self.start_dsl(single_dsl_folder, xms_option_value="64m", xmx_option_value="256m"):
                has_some_failures = True
        return has_some_failures

    # Méthode pour démarrer un DSL spécifique
    def start_dsl(self, dsl_folder_path: Path, xms_option_value: str = None, xmx_option_value: str = None) -> bool:
        print(f"Démarrage du DSL '{dsl_folder_path}'...")

        dsl_bin_dir_path = dsl_folder_path / "bin"
        results = list(dsl_bin_dir_path.glob("dsl-*.jar"))
        if len(results) != 1:
            print(f"Impossible de trouver un unique fichier JAR correspondant au composant DSL dans le dossier '{dsl_bin_dir_path}'")
            return False

        dsl_jar_path = results[0]

        command_arguments = [
            r"java",
            f"-Dname={dsl_folder_path.stem}",
            r"-Djava.security.egd=file:/dev/urandom",
            r"-Dvertx.logger-delegate-factory-class-name=io.vertx.core.logging.SLF4JLogDelegateFactory",
        ]

        if xms_option_value is not None:
            print(f"Démarrage de '{dsl_bin_dir_path}' avec l'option '-Xms{xms_option_value}'")
            command_arguments += [f"-Xms{xms_option_value}"]

        if xmx_option_value is not None:
            print(f"Démarrage de '{dsl_bin_dir_path}' avec l'option '-Xmx{xmx_option_value}'")
            command_arguments += [f"-Xmx{xmx_option_value}"]

        command_arguments += [
            r"-Dlog4j.configurationFile=./etc/dsl.log4j.xml",
            r"-jar", f"./bin/{dsl_jar_path.name}",
            r"-conf", r"./etc/dsl.json",
        ]

        if self.singleDslLogFolderPath.exists():
            shutil.rmtree(self.singleDslLogFolderPath, ignore_errors=True)
        self.singleDslLogFolderPath.mkdir(parents=True, exist_ok=True)

        dsl_log_file_path = self.logDirPath / self.consoleSingleDslLogFileName
        with dsl_log_file_path.open("w"):
            print(f"Détachement du processus...")
            process = run_detach_subprocess(dsl_log_file_path, command_arguments, current_working_directory=dsl_folder_path)
            print(f"PID du processus détaché: {process.pid}")

        print(f"Le DSL '{dsl_folder_path}' a été démarré")
        return True
    # Méthode pour arrêter tous les DSL individuels
    def stop_single_dsl(self) -> bool:
        # Initialisation du suivi des échecs
        has_some_failures = False
        # Récupération des dossiers DSL individuels
        single_dsl_folders = self.singleDslTargetDirPath.glob(f"*dsl-folder*")
        # Parcours de chaque dossier pour arrêter le DSL
        for single_dsl_folder in single_dsl_folders:
            # Si l'arrêt du DSL échoue, marquer l'échec
            if not self.stop_dsl(single_dsl_folder):
                has_some_failures = True
        return has_some_failures

    # Méthode pour arrêter un DSL individuel
    def stop_dsl(self, dsl_folder_path: Path) -> bool:
        import requests

        print(f"Arrêt du DSL '{dsl_folder_path}'...")

        # Chemin du fichier de configuration du DSL
        dsl_conf_path = dsl_folder_path / "etc" / "dsl.json"
        try:
            # Chargement du fichier JSON de configuration du DSL
            with dsl_conf_path.open("r") as json_file:
                dsl_conf_dict = json.load(json_file)
        except (OSError, json.JSONDecodeError) as e:
            print(f"    ! Échec du chargement du JSON depuis le fichier '{dsl_conf_path}': ", e)
            return False

        # Vérification si le JSON chargé est un dictionnaire
        if not isinstance(dsl_conf_dict, dict):
            print(f"    ! Le JSON du fichier '{dsl_conf_path}' n'est pas un dictionnaire ({dsl_conf_dict})")
            return False

        # Récupération de l'hôte et du port du DSL depuis le JSON chargé
        dsl_host = dsl_conf_dict.get("dsl.host", None)
        dsl_port = dsl_conf_dict.get("dsl.port", None)

        # Vérification de l'existence et de la validité de l'hôte et du port
        if dsl_host is None or dsl_port is None:
            print(f"    ! Impossible de récupérer l'hôte ou le port correct du DSL dans le dictionnaire ({dsl_conf_dict})")
            return False

        # Tentative d'envoi de la requête POST pour arrêter le DSL
        print(f"    - Tentative d'envoi sur l'URL 'http://{dsl_host}:{dsl_port}/api/v1/stop'...")
        try:
            r = requests.post(f"http://{dsl_host}:{dsl_port}/api/v1/stop", json=None)
        except requests.exceptions.RequestException as e:
            print(f"    Échec de l'envoi de la requête POST:", e)
        else:
            # Vérification de la réponse de la requête POST
            if r.status_code == requests.codes.ok:
                print(f"    - Requête POST réussie: {r.status_code}")
            else:
                print(f"    - Échec de la requête POST: {r.status_code}")
                # TODO: tuer le processus ?

        # Copie des logs du DSL individuel dans le dossier dédié
        print(f"    - Copie des logs du DSL individuel vers '{self.singleDslLogFolderPath}'")
        single_dsl_logs_folder_path = dsl_folder_path / "logs"
        single_dsl_log_files_path = list(single_dsl_logs_folder_path.glob(f"**/*.log"))
        for single_dsl_log_file_path in single_dsl_log_files_path:
            log_file_name_parts = single_dsl_log_file_path.name.split("..")
            target_log_file_path = self.singleDslLogFolderPath.joinpath(*log_file_name_parts)
            print(f"        - Copie du fichier log du DSL individuel '{single_dsl_log_file_path}' vers '{target_log_file_path}'")
            target_log_file_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(str(single_dsl_log_file_path), str(target_log_file_path))
            except OSError as e:
                print(f"            ! Échec de la copie : {e}")

        return True

    # Méthode statique pour vérifier si le dossier DSL est complet
    @staticmethod
    def check_dsl_folder_is_complete(dsl_dir_path: Path) -> bool:
        is_complete = (dsl_dir_path / "etc" / "dsl.json").is_file()
        is_complete &= (dsl_dir_path / "etc" / dsl_log_file).is_file()
        is_complete &= (dsl_dir_path / "bin").is_dir()
        is_complete &= (dsl_dir_path / "lib").is_dir()
        return is_complete

    # Méthode pour lister les DSL dans un dossier
    def list_the_dsl_in_folder(self) -> List[Path]:
        # Récupération des chemins des dossiers binaires DSL complets
        bin_folder_parent_results = sorted([p.parent for p in list(self.allDslRootDirPath.glob(f"**/bin")) if p.is_dir()])
        # Filtrage pour ne garder que les dossiers DSL complets
        dsl_results = [p for p in bin_folder_parent_results if self.check_dsl_folder_is_complete(p)]
        print(f"- Dossiers DSL dans le dossier racine des DSL:")
        for result_path in dsl_results:
            print(f"    - {result_path.relative_to(self.allDslRootDirPath)}")
        return dsl_results

    # Méthode pour fusionner les fichiers JAR des dossiers DSL dans un seul dossier
    def _merge_the_jar_files_from_dsl_folders_into_one_folder(self, jar_files_folder_name: str, dsl_dir_paths: List[Path]) -> NoReturn:
        # Création du dossier cible
        jar_files_target_dir_path = self.singleDslTargetDirPath / "main-dsl-folder" / jar_files_folder_name
        print(f"- Création du dossier cible pour les fichiers JAR '{jar_files_target_dir_path}'")
        jar_files_target_dir_path.mkdir(parents=True, exist_ok=True)

        # Fusion des fichiers
        print(f"- Fusion des fichiers JAR de chaque dossier 'DSL/{jar_files_folder_name}' dans le dossier cible '{jar_files_folder_name}'")
        exiting_jar_full_names: List[str] = []
        exiting_jar_versions_by_name: Dict[str, List[str]] = {}
        for dsl_dir_path in dsl_dir_paths:
            jar_path_results: List[Path] = list((dsl_dir_path / jar_files_folder_name).glob(f"./*.jar"))
            for jar_path in jar_path_results:
                jar_full_name = jar_path.name

                if jar_full_name not in exiting_jar_full_names:
                    # Mémorisation du nom complet du JAR
                    exiting_jar_full_names.append(jar_full_name)

                    # Copie du fichier JAR dans le dossier cible
                    shutil.copy2(str(jar_path), str(jar_files_target_dir_path))

                    # Récupération du nom et de la version du JAR
                    jar_nam_and_version_pattern = "^(?P<jar_name>(?:(?!-\d).)*)(-(?P<jar_version>\d+(?:(?!\.jar)\.\w+)*(?:-SNAPSHOT)*)|(\.jar))"
                    jar_name_and_version_math = re.match(jar_nam_and_version_pattern, jar_full_name)
                    if jar_name_and_version_math is None:
                        print(f"   ERROR: impossible de récupérer le nom et la version du JAR '{jar_path.relative_to(self.allDslRootDirPath)}' ! Aucune vérification supplémentaire...")
                        continue

                    jar_name = jar_name_and_version_math.group("jar_name")
                    jar_version = jar_name_and_version_math.group("jar_version")
                    if jar_name is None:
                        print(f"   ERROR: impossible de récupérer le nom du JAR '{jar_path.relative_to(self.allDslRootDirPath)}' ! Aucune vérification supplémentaire...")
                        continue

                    if jar_version is None:
                        jar_version = "non défini"

                    # Vérification de la présence de SNAPSHOT dans la version du JAR
                    if isinstance(jar_version, str) and "SNAPSHOT" in jar_version:
                        print(f"   ATTENTION: le JAR '{jar_path.relative_to(self.allDslRootDirPath)}' est en version SNAPSHOT !")

                    # Vérification de la présence du JAR dans une autre version
                    if jar_name in exiting_jar_versions_by_name.keys():
                        print(f"   ATTENTION: le JAR '{jar_path.relative_to(self.allDslRootDirPath)}' est présent dans une autre version !")

                    # Mémorisation de la version du JAR par son nom
                    exiting_jar_versions_by_name.setdefault(jar_name, []).append(jar_version)

        # Affichage des versions utilisées des fichiers JAR
        print(f"    - Résumé des versions utilisées des fichiers JAR par nom de fichier :")
        for jar_name, jar_versions in exiting_jar_versions_by_name.items():
            print(f"        - '{jar_name}' avec les versions : {jar_versions}")

    # Méthode pour fusionner les fichiers de ressources des dossiers DSL dans un seul dossier
    def _merge_the_resources_files_from_dsl_folders_into_one_folder(self, resources_files_folder_name: str,
                                                                    dsl_dir_paths: List[Path]) -> NoReturn:
        # Création du dossier cible
        resources_files_target_dir_path = self.singleDslTargetDirPath / "main-dsl-folder" / resources_files_folder_name
        print(f"- Création du dossier cible pour les fichiers de ressources '{resources_files_target_dir_path}'")
        resources_files_target_dir_path.mkdir(parents=True, exist_ok=True)

        # Fusion des fichiers
        print(f"- Fusion des fichiers de ressources de chaque dossier 'DSL/{resources_files_folder_name}' dans le dossier cible '{resources_files_folder_name}'")
        exiting_resource_relative_paths: List[Path] = []
        for dsl_dir_path in dsl_dir_paths:
            resource_file_path_results: List[Path] = [p for p in list((dsl_dir_path / resources_files_folder_name).glob(f"**/*"))if p.is_file()]
            for resource_path in resource_file_path_results:
                resource_relative_path = resource_path.relative_to(dsl_dir_path / resources_files_folder_name)

                if resource_relative_path not in exiting_resource_relative_paths:
                    # Mémorisation du chemin relatif des ressources
                    exiting_resource_relative_paths.append(resource_relative_path)

                    # Copie du fichier de ressources dans le dossier cible
                    resource_file_target_dir_path = resources_files_target_dir_path / resource_relative_path.parent
                    if not resource_file_target_dir_path.exists():
                        print(f"    - Création du dossier de ressources '{resource_file_target_dir_path.relative_to(self.singleDslTargetDirPath)}'")
                        resource_file_target_dir_path.mkdir(parents=True, exist_ok=True)
                    print(f"    - Copie du fichier '{resource_path.relative_to(self.allDslRootDirPath)}' vers le dossier cible"
                          f" '{resource_file_target_dir_path.relative_to(self.singleDslTargetDirPath)}'")
                    shutil.copy2(str(resource_path), str(resource_file_target_dir_path))

    # Méthode pour fusionner les fichiers autres que ceux de définition du DSL dans un seul dossier
    def _merge_the_files_other_than_the_dsl_definition_files_from_dsl_folders_into_one_folder(self, dsl_definition_file_names: List[str],
                                                                                              dsl_definition_files_folder_name: str,
                                                                                              dsl_dir_paths: List[Path]) -> NoReturn:
        # Création du dossier cible
        resources_files_target_dir_path = self.singleDslTargetDirPath / "main-dsl-folder" / dsl_definition_files_folder_name
        print(f"- Création du dossier cible pour les fichiers de définition du DSL '{dsl_definition_files_folder_name}'")
        resources_files_target_dir_path.mkdir(parents=True, exist_ok=True)

        # Fusion des fichiers
        print(f"- Fusion des fichiers de ressources de chaque dossier 'DSL/{dsl_definition_files_folder_name}' dans le dossier cible '{resources_files_target_dir_path}'")
        exiting_resource_relative_paths: List[Path] = []
        for dsl_dir_path in dsl_dir_paths:
            resource_file_path_results: List[Path] = [p for p in list(
                (dsl_dir_path / dsl_definition_files_folder_name).glob(f"**/*")) if
                                                      p.is_file() and p.name not in dsl_definition_file_names]
            for resource_path in resource_file_path_results:
                resource_relative_path = resource_path.relative_to(dsl_dir_path / dsl_definition_files_folder_name)

                if resource_relative_path not in exiting_resource_relative_paths:
                    # Mémorisation du chemin relatif des ressources
                    exiting_resource_relative_paths.append(resource_relative_path)

                    # Copie du fichier de ressources dans le dossier cible
                    resource_file_target_dir_path = resources_files_target_dir_path / resource_relative_path.parent
                    if not resource_file_target_dir_path.exists():
                        print(f"    - Création du dossier de ressources '{resource_file_target_dir_path.relative_to(self.singleDslTargetDirPath)}'")
                        resource_file_target_dir_path.mkdir(parents=True, exist_ok=True)
                    print(f"    - Copie du fichier '{resource_path.relative_to(self.allDslRootDirPath)}' vers le dossier cible"
                          f" '{resource_file_target_dir_path.relative_to(self.singleDslTargetDirPath)}'")
                    shutil.copy2(str(resource_path), str(resource_file_target_dir_path))
                else:
                    print(f"   ATTENTION: le nom de fichier des ressources '{resource_path.relative_to(self.allDslRootDirPath)}' existe déjà dans le dossier cible !")

    # Méthode statique pour obtenir un dictionnaire à partir d'un fichier JSON
    @staticmethod
    def _get_dict_from_json_file(json_file_path: Path) -> Optional[dict]:
        try:
            # Chargement du fichier JSON en tant que dictionnaire
            with json_file_path.open("r") as json_file:
                file_content_as_dict = json.load(json_file)
        except (OSError, json.JSONDecodeError) as e:
            print(f"        - Échec du chargement du JSON depuis le fichier '{json_file_path}' : ", e)
            return None

        # Vérification si le contenu chargé est un dictionnaire
        if not isinstance(file_content_as_dict, dict):
            print(f"        - Échec du chargement du JSON depuis le fichier '{json_file_path}' : le JSON lu n'est pas un dictionnaire ({file_content_as_dict})")
            return None

        return file_content_as_dict
    @staticmethod
    # Écrit un dictionnaire dans un fichier JSON. Renvoie True en cas de succès, False sinon.
    def _write_dict_to_json_file(input_dict: dict, output_json_file_path: Path) -> bool:
        try:
            # Ouvre le fichier JSON en écriture
            with output_json_file_path.open("w", newline="\n") as json_file:
                # Écrit le dictionnaire JSON dans le fichier avec une indentation de 4 espaces
                json.dump(input_dict, json_file, indent=4)
        except (OSError, TypeError, ValueError, OverflowError) as e:
            # En cas d'erreur, affiche un message d'erreur et renvoie False
            print(f"        - L'écriture du JSON dans le fichier '{output_json_file_path}' a échoué : ", e)
            return False
        # Renvoie True si l'écriture a réussi
        return True

    # Fusionne les fichiers JSON DSL de différents dossiers en un seul fichier.
    def _merge_the_dsl_json_file_from_dsl_folders_into_one_file(self, dsl_json_file_name: str,
                                                                dsl_definition_files_folder_name: str,
                                                                dsl_dir_paths: List[Path],
                                                                dsl_host="127.169.0.0", dsl_port=40000) -> Optional[Tuple[Optional[Path], Optional[List[Path]]]]:
        # Crée le dossier cible et le chemin du fichier JSON DSL unique
        dsl_folder_target_path = self.singleDslTargetDirPath / "main-dsl-folder"
        dsl_json_file_target_dir_path = dsl_folder_target_path / dsl_definition_files_folder_name
        print(f"- Crée le dossier cible du fichier JSON unique '{dsl_json_file_target_dir_path}'")
        dsl_json_file_target_dir_path.mkdir(parents=True, exist_ok=True)
        dsl_json_file_target_path = dsl_json_file_target_dir_path / dsl_json_file_name

        special_dsl_json_file_target_path_list = []

        # Fusionne les fichiers JSON DSL
        print(f"- Fusionne les fichiers {dsl_json_file_name} de chaque dossier 'DSL/{dsl_definition_files_folder_name}' en un seul fichier"
              f" {dsl_json_file_name} dans le dossier cible '{dsl_definition_files_folder_name}'")
        single_dsl_json_dict = {
            "dsl.host": dsl_host,
            "dsl.port": dsl_port,
            "components": [],
        }
        for dsl_dir_path_index, dsl_dir_path in enumerate(dsl_dir_paths):
            dsl_json_file_path = dsl_dir_path / dsl_definition_files_folder_name / dsl_json_file_name
            dsl_json_dict = self._get_dict_from_json_file(dsl_json_file_path)
            if dsl_json_dict is None:
                print(f"   ERREUR : impossible d'obtenir le contenu JSON du fichier DSL JSON '{dsl_json_file_path.relative_to(self.allDslRootDirPath)}'"
                      f" ! Continuer avec les autres fichiers {dsl_json_file_name}...")
                continue

            special_single_dsl_json_dict = {
                "dsl.host": dsl_host,
                "dsl.port": dsl_port + dsl_dir_path_index + 1,
                "components": [],
            }

            # Fusionne les composants dans le fichier JSON DSL unique
            dsl_json_components = dsl_json_dict.get("components", None)
            if not isinstance(dsl_json_components, list):
                print(f"   ERREUR : impossible d'obtenir la liste des composants depuis le fichier JSON DSL '{dsl_json_file_path.relative_to(self.allDslRootDirPath)}'"
                      f" ! Continuer avec les autres composants dans le fichier {dsl_json_file_name}...")
                continue
            for dsl_json_component_index, dsl_json_component in enumerate(dsl_json_components):
                dsl_json_component_jar = dsl_json_component.get("jar", None)
                if dsl_json_component_jar is None:
                    print(f"   ERREUR : impossible d'obtenir le champ 'jar' du composant #{dsl_json_component_index} depuis le fichier JSON DSL"
                          f" '{dsl_json_file_path.relative_to(self.allDslRootDirPath)}' ! Continuer avec les autres composants dans le fichier {dsl_json_file_name}...")
                    continue

                dsl_json_component_name = dsl_json_component.get("_name", None)
                if dsl_json_component_name is None:
                    print(f"   ERREUR : impossible d'obtenir le champ '_name' du composant #{dsl_json_component_index} depuis le fichier JSON DSL"
                          f" '{dsl_json_file_path.relative_to(self.allDslRootDirPath)}' ! Continuer avec les autres composants dans le fichier {dsl_json_file_name}...")
                    continue
                dsl_json_component_configuration_srv_instance = dsl_json_component.get("configuration", {}).get("srv.instance", None)
                if dsl_json_component_configuration_srv_instance is None:
                    print(f"   ERREUR : impossible d'obtenir le champ 'configuration/srv.instance' du composant '{dsl_json_component_name}'"
                          f" (#{dsl_json_component_name}) depuis le fichier JSON DSL '{dsl_json_file_path.relative_to(self.allDslRootDirPath)}'"
                          f" ! Continuer avec les autres composants dans le fichier {dsl_json_file_name}...")
                    continue

                # Construit la chaîne de topologie DSL
                dsl_topology_str = "..".join(dsl_dir_path.relative_to(self.allDslRootDirPath).parts)

                # Vérifie si les champs "_name" et "srv.instance" sont égaux
                if dsl_json_component_name != dsl_json_component_configuration_srv_instance:
                    print(f"   ATTENTION : le composant #{dsl_json_component_index} au nœud '{dsl_topology_str}' a une valeur de champ '_name'"
                          f" ('{dsl_json_component_name}') différente de la valeur 'srv.instance' ('{dsl_json_component_configuration_srv_instance}')")

                # Met à jour le nom du composant DSL
                updated_name = f"{dsl_topology_str}..{dsl_json_component_name}"
                dsl_json_component["_name"] = updated_name

                # Met à jour la configuration srv.instance du composant DSL
                updated_name = f"{dsl_topology_str}.{dsl_json_component_configuration_srv_instance}"
                dsl_json_component["configuration"]["srv.instance"] = updated_name

                # Ajoute le composant au fichier JSON DSL unique
                if dsl_json_component_jar.startswith("bin/generic-snmp") or dsl_json_component_jar.startswith("bin/dio-snmp-mock"):
                    special_single_dsl_json_dict["components"].append(dsl_json_component)
                else:
                    single_dsl_json_dict["components"].append(dsl_json_component)

            if len(special_single_dsl_json_dict["components"]) > 0:
                # Crée le dossier cible spécial et le chemin du fichier JSON DSL unique
                special_dsl_folder_target_path = self.singleDslTargetDirPath / f"dsl-folder-{```
            if len(special_single_dsl_json_dict["components"]) > 0:
                # Crée le dossier cible spécial et le chemin du fichier JSON DSL unique
                special_dsl_folder_target_path = self.singleDslTargetDirPath / f"dsl-folder-{special_single_dsl_json_dict['dsl.port']}"
                special_dsl_json_file_target_dir_path = special_dsl_folder_target_path / dsl_definition_files_folder_name
                print(f"- Crée le dossier cible du fichier JSON DSL spécial '{special_dsl_json_file_target_dir_path}'")
                special_dsl_json_file_target_dir_path.mkdir(parents=True, exist_ok=True)
                special_dsl_json_file_target_path = special_dsl_json_file_target_dir_path / dsl_json_file_name

                # Vérifie si l'écriture du dictionnaire spécial dans le fichier JSON a réussi
                if not self._write_dict_to_json_file(special_single_dsl_json_dict, special_dsl_json_file_target_path):
                    print(f"   ERREUR : impossible d'écrire le fichier JSON DSL unique '{special_dsl_json_file_target_path}' !")
                    return None

                # Ajoute le chemin du fichier JSON spécial à la liste
                special_dsl_json_file_target_path_list.append(special_dsl_json_file_target_path)

        # Écrit le fichier JSON DSL unique dans le dossier cible
        if not self._write_dict_to_json_file(single_dsl_json_dict, dsl_json_file_target_path):
            print(f"   ERREUR : impossible d'écrire le fichier JSON DSL unique '{dsl_json_file_target_path}' !")
            return None

        return dsl_json_file_target_path, special_dsl_json_file_target_path_list

    @staticmethod
    # Initialise les lignes XML de configuration du fichier de journalisation
    def _initialise_log_xml_lines() -> List[str]:
        return [
            r"""<?xml version="1.0" encoding="UTF-8"?>""",
            r"""<Configuration>""",
        ]

    @staticmethod
    # Ajoute un appendeur aux lignes XML de configuration du fichier de journalisation
    def _append_appender_to_log_xml_lines(dsl_log_xml_lines: list, log_dir: str, service_name: str, max_log_file_size: int) -> NoReturn:
        dsl_log_xml_lines.append(f"""        <RollingFile name="{service_name}" fileName="{log_dir}/{service_name}.log" filePattern="{log_dir}/{service_name}-%i.log" >""")
        dsl_log_xml_lines.append(r"""            <Policies>""")
        dsl_log_xml_lines.append(f"""               <SizeBasedTriggeringPolicy size="{max_log_file_size}"/>""")
        dsl_log_xml_lines.append(r"""            </Policies>""")
        dsl_log_xml_lines.append(r"""            <PatternLayout>""")
        dsl_log_xml_lines.append(r"""                <Pattern>%d{MM/dd HH:mm:ss.SSS} - %-5level - %replace{%-200msg}{'"password":"[^"]*"'}{'"password":"*****"'} %n</Pattern>""")
        dsl_log_xml_lines.append(r"""            </PatternLayout>""")
        dsl_log_xml_lines.append(r"""            <DefaultRolloverStrategy max="10"/>""")
        dsl_log_xml_lines.append(r"""        </RollingFile>""")
        dsl_log_xml_lines.append(r"""""")

    @staticmethod
    # Ajoute un enregistreur aux lignes XML de configuration du fichier de journalisation
    def _append_logger_to_log_xml_lines(dsl_log_xml_lines: list, service_name: str, namespace: str, trace_level: str) -> NoReturn:
        dsl_log_xml_lines.append(f"""        <Logger name="{namespace}" level="{trace_level}" additivity="false">""")
        dsl_log_xml_lines.append(f"""            <AppenderRef ref="{service_name}"/>""")
        dsl_log_xml_lines.append(r"""        </Logger>""")

    @staticmethod
    # Écrit les lignes XML de configuration du fichier de journalisation dans un fichier
    def _write_log_xml_lines(dsl_log_xml_lines: list, dsl_log_xml_path: Path) -> bool:
        dsl_log_xml_lines.append(r"""        <Root level="WARN">""")
        dsl_log_xml_lines.append(r"""            <AppenderRef ref="dsl" />""")
        dsl_log_xml_lines.append(r"""        </Root>""")
        dsl_log_xml_lines.append(r"""    </Loggers>""")
        dsl_log_xml_lines.append(r"""</Configuration>""")

        try:
            # Écrit les lignes XML dans le fichier
            with dsl_log_xml_path.open("w", newline="\n") as target:
                target.writelines([f"{line}\n" for line in dsl_log_xml_lines])
        except (OSError, TypeError, ValueError) as e:
            print(f"        - Échec de l'écriture du fichier '{dsl_log_xml_path}' : ", e)
            return False

        return True

    def _build_the_single_dsl_log_xml_file_from_the_single_dsl_json_file(self, dsl_log_xml_file_name: str,
                                                                         dsl_json_file_path: Path,
                                                                         trace_level: str = "DEBUG",
                                                                         max_log_file_size: int = 10240000) -> bool:
        # Crée le chemin du fichier log4j.xml DSL unique
        dsl_log_xml_file_path = dsl_json_file_path.parent / dsl_log_xml_file_name

        # Construit le fichier log4j DSL
        print(f"- Construit le fichier unique {dsl_log_xml_file_name} DSL à partir du fichier DSL unique '{dsl_json_file_path}'")
        print(f"    - Initialise les lignes du fichier unique {dsl_log_xml_file_name} DSL")
        dsl_log_xml_lines = self._initialise_log_xml_lines()
        dsl_json_dict = self._get_dict_from_json_file(dsl_json_file_path)
        dsl_namespaces_by_service_name = {"dsl": ["dsl"]}
        if dsl_json_dict is None:
            print(f"   ERREUR : impossible d'obtenir le contenu JSON du fichier DSL JSON '{dsl_json_file_path}' !")
            return False
        for dsl_json_component_index, dsl_json_component in enumerate(dsl_json_dict.get("components", [])):
            dsl_json_component_enable_status = dsl_json_component.get("enable", True)
            if not dsl_json_component_enable_status:
                continue

            dsl_json_component_jar = dsl_json_component.get("jar", None)
            if dsl_json_component_jar is None:
                print(f"   ERREUR : impossible d'obtenir le champ 'jar' du composant #{dsl_json_component_index} depuis le fichier JSON DSL '{dsl_json_file_path}' !")
                return False

            dsl_json_component_name = dsl_json_component.get("_name", None)
            if dsl_json_component_name is None:
                print(f"   ERREUR : impossible d'obtenir le champ '_name' du composant #{dsl_json_component_index} depuis le fichier JSON DSL '{dsl_json_file_path}' !")
                return False

            dsl_json_component_configuration_srv_instance = dsl_json_component.get("configuration", {}).get("srv.instance", None)
            if dsl_json_component_configuration_srv_instance is None:
                print(f"   ERREUR : impossible d'obtenir le champ 'configuration/srv.instance' du composant"
                      f" '{dsl_json_component_name}' (#{dsl_json_component_name}) depuis le fichier JSON DSL '{dsl_json_file_path}' !")
                return False

            # Construit la liste des composants pour générer les enregistreurs et les appendices
            # Gestion spéciale pour RM-MOCK
            elif dsl_json_component_jar.startswith("bin/rm-mock-"):
                remote_identifier = dsl_json_component.get("configuration", {}).get("remote.identifier", None)
                if remote_identifier is not None:
                    dsl_namespaces_by_service_name[dsl_json_component_configuration_srv_instance] = [remote_identifier]
            # Cas normal
            else:
                dsl_namespaces_by_service_name[dsl_json_component_configuration_srv_instance] = [dsl_json_component_configuration_srv_instance]

        # Ajoute les appendices
        dsl_log_xml_lines.append(r"""    <Appenders>""")
        for service_name in dsl_namespaces_by_service_name.keys():
            # print(f"    - Ajoute la configuration du composant '{dsl_json_component_name}' aux lignes du fichier unique {dsl_log_xml_file_name} DSL")
            self._append_appender_to_log_xml_lines(dsl_log_xml_lines, "logs", service_name, max_log_file_size)
        dsl_log_xml_lines.append(r"""    </Appenders>""")

        # Ajoute les enregistreurs
        dsl_log_xml_lines.append(r"""    <Loggers>""")
        for service_name, namespaces in dsl_namespaces_by_service_name.items():
            for namespace in namespaces:
                # Crée les enregistreurs
                self._append_logger_to_log_xml_lines(dsl_log_xml_lines, service_name, namespace, trace_level)

        print(f"    - Écrit le fichier unique {dsl_log_xml_file_name} DSL '{dsl_log_xml_file_path}'")
        if not self._write_log_xml_lines(dsl_log_xml_lines, dsl_log_xml_file_path):
            return False
        return True
