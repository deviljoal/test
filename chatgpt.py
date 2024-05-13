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


