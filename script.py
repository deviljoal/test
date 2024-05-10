# -*- coding: utf-8 -*-

# Version: 23/09/12 15:28:24 - 70022070d76f7b0703b2aedf4e9c8e70632304dee23776d9d33373aea132dbfc

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

dsl_log_file = "dsl.log4j.xml"

def adapt_the_command_arguments_when_using_bash_on_windows(command_arguments):
    command_arguments_to_use = command_arguments[:]
    if platform.system() == "Windows":
        command_arguments_to_use = ["bash.exe", "-c", " ".join(command_arguments)]
    return command_arguments_to_use


def run_subprocess(log_file_path: Path,
                   arguments: Union[list, str],
                   *subprocess_args,
                   environment_variables: dict = None,
                   current_working_directory: Path = None,
                   **subprocess_kwargs) -> subprocess.Popen:
    with subprocess.Popen(arguments, *subprocess_args,
                          env=environment_variables,
                          cwd=current_working_directory,
                          text=True,
                          stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT,
                          bufsize=1,
                          **subprocess_kwargs) as running_process, log_file_path.open("w") as log_file:
        for line in running_process.stdout:
            line = datetime.now().strftime("%H:%M:%S.%f")[:-3] + "- " + line
            print(line[:-1])
            log_file.write(line)
            log_file.flush()
    return running_process


def run_detach_subprocess(log_file_path: Path,
                          arguments: list,
                          environment_variables: dict = None,
                          current_working_directory: Path = None) -> subprocess.Popen:
    def norm_path(file_path: Path) -> str:
        return str(file_path).replace('\\', '/')

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

    if platform.system() == "Windows":
        process = subprocess.Popen(python_command_arguments, cwd=current_working_directory.parent, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        process = subprocess.Popen(python_command_arguments, cwd=current_working_directory.parent, start_new_session=True)    # Try adding this in case of terminal problems: , stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    return process


class DictPath:

    @classmethod
    def is_a_path_step_as_index(cls, path_step):
        if isinstance(path_step, int) and path_step >= 0:
            return True
        return False

    @classmethod
    def is_a_path_step_as_key(cls, path_step):
        if isinstance(path_step, str):
            return True
        return False

    def __init__(self, from_dict_path: DictPath = None, from_dict_path_as_list: Optional[List[str]] = None):
        if from_dict_path_as_list is not None:
            self.dictPath = from_dict_path_as_list[:]
        elif from_dict_path is None:
            self.dictPath = []
        else:
            self.dictPath = from_dict_path.get_dict_path_as_list()

    def __str__(self):
        return "->".join([str(x) for x in self.dictPath])

    def get_dict_path_as_list(self):
        return self.dictPath[:]

    def is_empty(self):
        return len(self.dictPath) == 0

    def add_a_step_to_the_path(self, path_step):
        if not self.is_a_path_step_as_key(path_step) and not self.is_a_path_step_as_index(path_step):
            raise UserWarning(f"Unexpected path step type (expected string or positive int)")
        self.dictPath = [path_step] + self.dictPath

    def get_the_last_step_of_the_path(self):
        if self.is_empty():
            return None
        return self.dictPath[0]

    def get_the_path_to_parent(self):
        if self.is_empty():
            return None
        return DictPath(from_dict_path_as_list=self.dictPath[1:])

    def get_the_path_to_a_following_step(self, following_path_step: Union[str, int]) -> NoReturn:
        new_dict_path = DictPath(from_dict_path=self)
        new_dict_path.add_a_step_to_the_path(following_path_step)
        return new_dict_path

    def pop_the_last_step_of_the_path(self):
        return self.dictPath.pop(0)

    def pop_the_first_step_of_the_path(self):
        return self.dictPath.pop()


class PathBasedDictionary:

    def __init__(self, root_dict: dict):
        self.root_dict = root_dict

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

    def replace_the_last_key_given_by_a_dict_path(self, dict_path: DictPath, new_last_key: str, new_pointed_value: Optional[Any] = None) -> NoReturn:
        key = dict_path.get_the_last_step_of_the_path()
        if not DictPath.is_a_path_step_as_key(key):
            raise UserWarning(f"The path '{dict_path}' last step is not a key")
        parent_dict = self.get_the_value_pointed_by_a_dict_path(dict_path.get_the_path_to_parent())
        if not isinstance(parent_dict, dict):
            raise UserWarning(f"The path '{dict_path}' last step parent is not a dict")

        if new_pointed_value is not None:
            value = new_pointed_value
        else:
            value = self.get_the_value_pointed_by_a_dict_path(dict_path)

        key_position = list(parent_dict.keys()).index(key)
        parent_items = list(parent_dict.items())
        parent_items.insert(key_position, (new_last_key, value))
        new_parent_dict = dict(parent_items)
        new_parent_dict.pop(key, None)

        parent_dict.clear()
        parent_dict.update(new_parent_dict)

    def delete_the_last_key_given_by_a_dict_path(self, dict_path: DictPath) -> NoReturn:
        key = dict_path.get_the_last_step_of_the_path()
        if not DictPath.is_a_path_step_as_key(key):
            raise UserWarning(f"The path '{dict_path}' last step is not a key")
        parent_dict = self.get_the_value_pointed_by_a_dict_path(dict_path.get_the_path_to_parent())
        if not isinstance(parent_dict, dict):
            raise UserWarning(f"The path '{dict_path}' last step parent is not a dict")

        parent_dict.pop(key, None)


class DictionaryParser:
    IGNORE_THE_KEY = "--ignore-the-key--"
    DELETE_THE_KEY = "--delete-the-key--"

    def __init__(self, callback_on_key_analysis_starting: Callable[[str, DictPath, PathBasedDictionary], Optional[str]],
                 callback_on_key_analysis_ending: Callable[[str, DictPath, PathBasedDictionary], NoReturn],
                 callback_on_the_value_at_the_end_of_an_analyzed_path: Callable[[DictPath, PathBasedDictionary], bool]):

        self.callback_on_key_analysis_starting = callback_on_key_analysis_starting
        self.callback_on_key_analysis_ending = callback_on_key_analysis_ending
        self.callback_on_the_value_at_the_end_of_an_analyzed_ = callback_on_the_value_at_the_end_of_an_analyzed_path

    def parse_dict(self, dict_to_parse: dict):
        self._parse_path_base_dict(PathBasedDictionary(dict_to_parse))

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

    def is_a_deployment_description_parser_key_word(self, key: str) -> bool:
        key_words_in_key = [key_word in key for key_word in self.key_words.values()]
        return True in key_words_in_key

    def is_a_correct_node_or_component_name(self, key: str) -> bool:
        not_allowed_key_words = list(self.key_words.values())[:]
        not_allowed_key_words.remove(self.key_words["label_of_is_present_test"])
        not_allowed_key_words.remove(self.key_words["label_of_a_template_definition"])
        not_allowed_key_words.remove(self.key_words["label_of_a_template_use"])
        not_allowed_key_words.remove(self.key_words["label_of_an_just_to_differentiate_at_building_time"])

        key_words_in_key = [key_word in key for key_word in not_allowed_key_words]
        return not (True in key_words_in_key)

    def parse_deployment_description_dict(self, deployment_dict: dict) -> NoReturn:
        self._dictionaryParser.parse_dict(deployment_dict)

    def _process_key_starting(self, new_key_in_the_path: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> Optional[str]:
        raise UserWarning(f"'_process_key_starting' function must be overridden")

    def _process_key_ending(self, new_key_in_the_path: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        raise UserWarning(f"'_process_key_ending' function must be overridden")

    def _process_final_value(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> bool:
        raise UserWarning(f"'_process_final_value' function must be overridden")

    def _deep_update(self, original_dict: dict, update_dict: dict) -> dict:
        for key, value in update_dict.items():
            if isinstance(value, dict):
                original_dict[key] = self._deep_update(original_dict.setdefault(key, {}), value)
            else:
                original_dict[key] = value
        # TODO: List ?
        return original_dict

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

    @staticmethod
    def _write_dict_to_json_file(input_dict: dict, output_json_file_path: Path) -> NoReturn:
        try:
            with output_json_file_path.open("w", newline="\n") as json_file:
                json.dump(input_dict, json_file, indent=4)
        except (OSError, TypeError, ValueError, OverflowError) as e:
            print(f"Write json to file '{output_json_file_path}' failed: ", e)
            raise UserWarning(f"Write json file '{output_json_file_path}' from dict failed: {e}")

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

    def _get_parent_component_group_dict_path(self, dict_path: DictPath) -> Optional[DictPath]:
        working_dict_path = DictPath(from_dict_path=dict_path)

        while not working_dict_path.is_empty():
            while DictPath.is_a_path_step_as_index(working_dict_path.get_the_last_step_of_the_path()):
                working_dict_path.pop_the_last_step_of_the_path()

            last_path_step = working_dict_path.get_the_last_step_of_the_path()
            if last_path_step == self.key_words["label_of_a_node_dictionary"]:
                return None
            if last_path_step.startswith(self.key_words["label_of_a_components_group"]):
                return working_dict_path

            working_dict_path.pop_the_last_step_of_the_path()

        return None

    def _is_parent_group_is_the_main_parent_group(self, dict_path: DictPath) -> bool:
        parent_group_dict_path = self._get_parent_component_group_dict_path(dict_path)
        if parent_group_dict_path is None:
            return False

        parent_group_dict_path_as_list_without_him = parent_group_dict_path.get_dict_path_as_list()[1:]
        for dict_path_step in parent_group_dict_path_as_list_without_him:
            if dict_path_step.startswith(self.key_words["label_of_a_components_group"]):
                return False
        return True

    def _get_main_parent_component_group_dict_path(self, dict_path: DictPath) -> Optional[DictPath]:
        working_dict_path = DictPath(from_dict_path=dict_path)

        candidate_dict_path = None

        while not working_dict_path.is_empty():
            while DictPath.is_a_path_step_as_index(working_dict_path.get_the_last_step_of_the_path()):
                working_dict_path.pop_the_last_step_of_the_path()

            last_path_step = working_dict_path.get_the_last_step_of_the_path()
            if last_path_step == self.key_words["label_of_a_node_dictionary"]:
                break
            if last_path_step.startswith(self.key_words["label_of_a_components_group"]):
                candidate_dict_path = DictPath(from_dict_path=working_dict_path)

            working_dict_path.pop_the_last_step_of_the_path()

        return candidate_dict_path

    def _get_parents_component_groups_names(self, dict_path: DictPath) -> Optional[List[str]]:
        parents_component_groups_names = []
        working_dict_path = DictPath(from_dict_path=dict_path)

        while not working_dict_path.is_empty():
            while DictPath.is_a_path_step_as_index(working_dict_path.get_the_last_step_of_the_path()):
                working_dict_path.pop_the_last_step_of_the_path()

            last_path_step = working_dict_path.get_the_last_step_of_the_path()
            parent_dict_path = working_dict_path.get_the_path_to_parent()
            if parent_dict_path is not None:
                if last_path_step.startswith(self.key_words["label_of_a_components_group"]):
                    parents_component_groups_names.append(self._get_group_name_from_definition_key(last_path_step))

            working_dict_path.pop_the_last_step_of_the_path()

        return parents_component_groups_names

    def _get_group_name_from_definition_key(self, group_name_definition_key):
        return group_name_definition_key[group_name_definition_key.find(self.key_words["label_of_a_components_group"]) + len(self.key_words["label_of_a_components_group"]):]

    def _search_by_deployment_path(self, parameter_deployment_path_as_string: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> Tuple[Optional[Union[str, int, float, bool, list, dict]], Optional[dict], Optional[DictPath]]:
        working_parameter_path = parameter_deployment_path_as_string.split("/")

        first_relative_deployment_path_step = working_parameter_path[0]
        _, _, first_relative_deployment_path_step_parent_dict_path = self._search_from_here_to_the_top_of_the_parameter_value(first_relative_deployment_path_step, dict_path, path_based_dict)
        if first_relative_deployment_path_step_parent_dict_path is None:
            # raise UserWarning(f"The '{dict_path}' parameter reference '{first_relative_deployment_path_step}' not found")
            potential_component_group_name = self.key_words["label_of_a_components_group"] + first_relative_deployment_path_step
            _, _, first_relative_deployment_path_step_parent_dict_path = self._search_from_here_to_the_top_of_the_parameter_value(potential_component_group_name, dict_path, path_based_dict)
            if first_relative_deployment_path_step_parent_dict_path is None:
                raise UserWarning(f"The '{dict_path}' parameter reference '{first_relative_deployment_path_step}' not found")

        dict_path = first_relative_deployment_path_step_parent_dict_path
        param_value = None
        param_parent_dict = None
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

    @staticmethod
    def _search_from_here_to_the_top_of_the_parameter_value(parameter: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> Tuple[Optional[Union[str, int, float, bool, list, dict]], Optional[dict], Optional[DictPath]]:
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

        working_dict_path = DictPath(from_dict_path=dict_path)
        last_dict_key_checked = None
        while not working_dict_path.is_empty():
            while DictPath.is_a_path_step_as_index(working_dict_path.get_the_last_step_of_the_path()):
                working_dict_path.pop_the_last_step_of_the_path()

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

    def clean_deployment_description_dict(self, deployment_description_dict: dict) -> NoReturn:
        self.parse_deployment_description_dict(deployment_description_dict)

    def _process_key_starting(self, new_key_in_the_path: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> Optional[str]:
        parent_path_step = dict_path.get_the_last_step_of_the_path()
        great_parent_path_step = dict_path.get_the_path_to_parent()
        if great_parent_path_step is not None:
            great_parent_path_step = great_parent_path_step.get_the_last_step_of_the_path()

        if parent_path_step is None:
            if not self.is_a_deployment_description_parser_key_word(new_key_in_the_path):
                return DictionaryParser.DELETE_THE_KEY

        if self.key_words["label_of_a_template_definition"] in new_key_in_the_path:
            return DictionaryParser.DELETE_THE_KEY

        if great_parent_path_step == self.key_words["label_of_a_node_dictionary"]:
            if not self.is_a_deployment_description_parser_key_word(new_key_in_the_path):
                return DictionaryParser.DELETE_THE_KEY

        if isinstance(parent_path_step, str) and parent_path_step.startswith(self.key_words["label_of_a_components_group"]):
            if not self.is_a_deployment_description_parser_key_word(new_key_in_the_path):
                return DictionaryParser.DELETE_THE_KEY

        if great_parent_path_step == self.key_words["label_of_a_component_dictionary"]:
            if not self.is_a_deployment_description_parser_key_word(new_key_in_the_path):
                return DictionaryParser.DELETE_THE_KEY

        # if parent_path_step == self.key_words["label_of_a_component_dictionary"]:
        #     return DictionaryParser.IGNORE_THE_KEY

        if parent_path_step == self.key_words["label_of_a_pel_section"]:
            return DictionaryParser.IGNORE_THE_KEY

        if parent_path_step == self.key_words["label_of_a_pil_section"]:
            return DictionaryParser.IGNORE_THE_KEY

        if parent_path_step == self.key_words["label_of_a_jaeger_section"]:
            return DictionaryParser.IGNORE_THE_KEY

        return new_key_in_the_path

    def _process_key_ending(self, new_key_in_the_path: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        pass

    def _process_final_value(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> bool:
        is_value_updated = False
        return is_value_updated


class DeploymentDescriptionBuilder(DeploymentDescriptionParser):

    def __init__(self, component_config_dir_path: Path = None):
        DeploymentDescriptionParser.__init__(self)

        self.componentConfigDirPath = component_config_dir_path

    def parse_deployment_description_from_json_file_to_json_file(self, json_file_path_source: Path, deployment_target: str, json_file_path_destination: Path) -> NoReturn:
        deployment_dict = self._get_dict_from_json_file(json_file_path_source)

        deployment_dict[self.key_words["label_of_the_deployment_target"]] = deployment_target

        self.parse_deployment_description_dict(deployment_dict)

        json_file_path_destination.parent.mkdir(parents=True, exist_ok=True)
        if json_file_path_destination.exists():
            json_file_path_destination.unlink()

        deployment_description_cleaner = DeploymentDescriptionCleaner()
        deployment_description_cleaner.clean_deployment_description_dict(deployment_dict)
        self._write_dict_to_json_file(deployment_dict, json_file_path_destination)

    def _process_key_starting(self, new_key_in_the_path: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> Optional[str]:
        parent_path_step = dict_path.get_the_last_step_of_the_path()

        if new_key_in_the_path.startswith("! "):
            return DictionaryParser.DELETE_THE_KEY

        if self.key_words["label_of_an_just_to_differentiate_at_building_time"] in new_key_in_the_path:
            dict_path_to_key = dict_path.get_the_path_to_a_following_step(new_key_in_the_path)
            new_key_in_the_path = new_key_in_the_path[:new_key_in_the_path.find(self.key_words["label_of_an_just_to_differentiate_at_building_time"])]
            path_based_dict.replace_the_last_key_given_by_a_dict_path(dict_path_to_key, new_key_in_the_path)

        if self.key_words["label_of_a_template_definition"] in new_key_in_the_path:
            return DictionaryParser.IGNORE_THE_KEY

        if self.key_words["label_of_is_present_test"] in new_key_in_the_path:
            new_key = self._replace_conditional_key(new_key_in_the_path, dict_path, path_based_dict)
            if new_key is None:
                return DictionaryParser.DELETE_THE_KEY
        else:
            new_key = self._replace_referenced_key(new_key_in_the_path, dict_path, path_based_dict)

        if self.key_words["label_of_a_template_use"] in new_key:
            new_key = self._replace_templated_key(new_key, dict_path, path_based_dict)

        if parent_path_step == self.key_words["label_of_a_node_dictionary"]:
            for path_step in dict_path.get_dict_path_as_list():
                if self.key_words["label_of_a_components_group"] in path_step or self.key_words["label_of_a_component_dictionary"] in path_step:
                    raise UserWarning(f"The '{dict_path}' to the key '{new_key}' contains component group or component dictionary")

            self._add_node_name_key(new_key, dict_path, path_based_dict)

        if new_key.startswith(self.key_words["label_of_a_components_group"]):
            self._add_component_group_name_key(new_key, dict_path, path_based_dict)

        if parent_path_step == self.key_words["label_of_a_component_dictionary"]:
            if not self.is_a_correct_node_or_component_name(new_key_in_the_path):
                raise UserWarning(f"The '{dict_path}' key '{new_key}' is not a component name")

            self._add_component_description_name_key(new_key, dict_path, path_based_dict)
            if self.componentConfigDirPath is not None:
                self._check_component_description_name_key(new_key, dict_path, path_based_dict)

        return new_key

    def _replace_conditional_key(self, conditional_key: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> Optional[str]:
        dict_path_to_conditional_key = dict_path.get_the_path_to_a_following_step(conditional_key)
        new_key = conditional_key[:conditional_key.find(self.key_words["label_of_is_present_test"])]
        presence_condition = conditional_key[conditional_key.find(self.key_words["label_of_is_present_test"]):]

        referenced_presence_condition = self._replace_references_in_value(presence_condition, dict_path, path_based_dict)

        if referenced_presence_condition == self.key_words["label_of_is_present_test"] + "True":
            path_based_dict.replace_the_last_key_given_by_a_dict_path(dict_path_to_conditional_key, new_key)
            return new_key

        return None

    def _process_key_ending(self, new_key_in_the_path: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        pass

    def _process_final_value(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> bool:
        is_value_updated = False
        is_value_updated |= self._replace_templated_final_value(dict_path, path_based_dict)
        is_value_updated |= self._replace_referenced_final_value(dict_path, path_based_dict)
        return is_value_updated

    def _replace_referenced_key(self, referenced_key: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> str:
        new_key = self._replace_references_in_value(referenced_key, dict_path, path_based_dict)
        if new_key == referenced_key:
            return referenced_key

        dict_path_to_referenced_key = dict_path.get_the_path_to_a_following_step(referenced_key)
        path_based_dict.replace_the_last_key_given_by_a_dict_path(dict_path_to_referenced_key, new_key)
        return new_key

    def _replace_referenced_final_value(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> bool:
        referenced_value = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path)
        if not isinstance(referenced_value, str):
            return False

        new_value = self._replace_references_in_value(referenced_value, dict_path, path_based_dict)
        if new_value == referenced_value:
            return False

        path_based_dict.set_the_value_pointed_by_a_dict_path(new_value, dict_path)

        return True

    def _replace_templated_key(self, templated_key: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> str:
        dict_path_to_templated_key = dict_path.get_the_path_to_a_following_step(templated_key)
        current_value = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path_to_templated_key)
        new_key = templated_key[:templated_key.find(self.key_words["label_of_a_template_use"])]
        template_to_use = templated_key[templated_key.find(self.key_words["label_of_a_template_use"]):]
        template_name = self.key_words["label_of_a_template_definition"] + template_to_use[len(self.key_words["label_of_a_template_use"]):]
        if len(template_name) == 0:
            raise UserWarning(f"The '{dict_path}' template in key '{templated_key}' not define")

        referenced_template_name = self._replace_references_in_value(template_name, dict_path, path_based_dict)

        template_value, _, _ = self._search_from_here_to_the_top_of_the_parameter_value(referenced_template_name, dict_path, path_based_dict)
        if template_value is None:
            raise UserWarning(f"The '{dict_path}' template in key '{templated_key}' not found")

        new_value = copy.deepcopy(template_value)

        if isinstance(new_value, dict) and isinstance(current_value, dict):
            self._deep_update(new_value, current_value)

        path_based_dict.replace_the_last_key_given_by_a_dict_path(dict_path_to_templated_key, new_key, new_value)

        return new_key

    def _replace_templated_final_value(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> bool:
        templated_value = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path)
        if not isinstance(templated_value, str) or not templated_value.startswith(f"{self.key_words['label_of_a_template_use']}"):
            return False

        template_to_use = templated_value[templated_value.find(self.key_words["label_of_a_template_use"]):]
        template_name = self.key_words["label_of_a_template_definition"] + template_to_use[len(self.key_words["label_of_a_template_use"]):]
        if len(template_name) == 0:
            raise UserWarning(f"The '{dict_path}' template in value '{templated_value}' not define")

        referenced_template_name = self._replace_references_in_value(template_name, dict_path, path_based_dict)

        template_value, _, _ = self._search_from_here_to_the_top_of_the_parameter_value(referenced_template_name, dict_path, path_based_dict)
        if template_value is None:
            raise UserWarning(f"The '{dict_path}' template in value '{templated_value}' not found")

        new_value = copy.deepcopy(template_value)
        path_based_dict.set_the_value_pointed_by_a_dict_path(new_value, dict_path)

        return True

    def _add_node_name_key(self, node_definition_key: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        dict_path_to_node_definition_key = dict_path.get_the_path_to_a_following_step(node_definition_key)
        current_value = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path_to_node_definition_key)
        if not isinstance(current_value, dict):
            raise UserWarning(f"The '{dict_path}' node '{node_definition_key}' is not a dict as value type")

        if self.key_words["label_of_the_node_name"] in current_value.keys():
            raise UserWarning(f"The '{dict_path}' node '{node_definition_key}' already defined a '{self.key_words['label_of_the_node_name']}'")

        new_node_definition_value = {self.key_words["label_of_the_node_name"]: node_definition_key, **current_value}
        path_based_dict.set_the_value_pointed_by_a_dict_path(new_node_definition_value, dict_path_to_node_definition_key)

    def _add_component_group_name_key(self, group_name_definition_key: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        dict_path_to_group_name_definition_key = dict_path.get_the_path_to_a_following_step(group_name_definition_key)
        current_value = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path_to_group_name_definition_key)
        if not isinstance(current_value, dict):
            raise UserWarning(f"The '{dict_path}' component group defined in key '{group_name_definition_key}' has not a dict as value type")

        group_name = self._get_group_name_from_definition_key(group_name_definition_key)
        if group_name == "":
            raise UserWarning(f"The '{dict_path}' component group defined in key '{group_name_definition_key}' has no component group name defined")

        if self.key_words["label_of_the_components_group_name"] in current_value:
            raise UserWarning(f"The '{dict_path}' component group name '{group_name}' already defined a '{self.key_words['label_of_the_components_group_name']}'")

        new_group_definition_value = {self.key_words["label_of_the_components_group_name"]: group_name, **current_value}
        path_based_dict.set_the_value_pointed_by_a_dict_path(new_group_definition_value, dict_path_to_group_name_definition_key)

    def _add_component_description_name_key(self, component_description_definition_key: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        dict_path_to_component_description_definition_key = dict_path.get_the_path_to_a_following_step(component_description_definition_key)
        current_value = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path_to_component_description_definition_key)
        if not isinstance(current_value, dict):
            raise UserWarning(f"The '{dict_path}' component description '{component_description_definition_key}' is not a dict as value type")

        if self.key_words["label_of_the_component_description_name"] in current_value.keys():
            raise UserWarning(f"The '{dict_path}' component description '{component_description_definition_key}' already defined a '{self.key_words['label_of_the_component_description_name']}'")

        if self.key_words["label_of_the_component_name"] not in current_value.keys():
            raise UserWarning(f"The '{dict_path}' component description '{component_description_definition_key}' doesn't defined a '{self.key_words['label_of_the_component_name']}'")

        if self.key_words["label_of_a_component_env_var_dictionary"] not in current_value.keys():
            raise UserWarning(f"The '{dict_path}' component description '{component_description_definition_key}' doesn't defined a '{self.key_words['label_of_the_component_name']}'")

        new_component_description_value = {self.key_words["label_of_the_component_description_name"]: component_description_definition_key, **current_value}
        path_based_dict.set_the_value_pointed_by_a_dict_path(new_component_description_value, dict_path_to_component_description_definition_key)

    def _check_component_description_name_key(self, component_description_definition_key: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        dict_path_to_component_description_definition_key = dict_path.get_the_path_to_a_following_step(component_description_definition_key)
        current_value = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path_to_component_description_definition_key)
        component_deployment_name = "/".join(self._get_deployment_path(dict_path))

        component_name = current_value.get(self.key_words["label_of_the_component_name"], None)
        referenced_component_name = self._replace_references_in_value(component_name, dict_path_to_component_description_definition_key, path_based_dict)
        component_env_var_dictionary = current_value.get(self.key_words["label_of_a_component_env_var_dictionary"], None)
        component_env_var_dictionary_without_key_word = {k if self.key_words["label_of_is_present_test"] not in k else k[:k.find(self.key_words["label_of_is_present_test"])]: v for (k, v) in component_env_var_dictionary.items()}

        equinox_sh_value_by_component_parameter_name, additional_equinox_sh_value_by_component_parameter_name = self._get_component_configuration_from_config_equinox_sh(referenced_component_name)

        additional_equinox_sh_parameter = set()
        for additional_parameters_list in additional_equinox_sh_value_by_component_parameter_name.values():
            additional_equinox_sh_parameter = additional_equinox_sh_parameter.union(set(additional_parameters_list))

        if "!!! FILLED AT BUILDING TIME !!!" in component_env_var_dictionary:
            print(f"     !! Build warning: the '{component_deployment_name}' ('{referenced_component_name}') component description was filled from equinox content")

            component_parameters_dict = equinox_sh_value_by_component_parameter_name

            for component_parameter, additional_parameters in additional_equinox_sh_value_by_component_parameter_name.items():
                for additional_parameter in additional_parameters:
                    component_parameters_dict[additional_parameter] = f"associated to '{component_parameter}'"

            component_env_var_dictionary.clear()
            component_env_var_dictionary.update(component_parameters_dict)
        else:
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

        path_based_dict.set_the_value_pointed_by_a_dict_path(current_value, dict_path_to_component_description_definition_key)

    def _replace_references_in_value(self, value: Union[str, int, float, bool, list, dict], dict_path: DictPath, path_based_dict: PathBasedDictionary) -> Optional[Union[str, int, float, bool, list, dict]]:
        output_value = value

        output_value = self._replace_references_on_parameter_in_value(output_value, dict_path, path_based_dict)

        safe_locals_dict_to_use = {
            "wp": dict_path.get_dict_path_as_list(),
        }

        output_value = self._replace_references_on_lambdas_in_value(output_value, dict_path, path_based_dict, safe_locals_dict=safe_locals_dict_to_use)
        output_value = self._replace_references_on_evaluations_in_value(output_value, safe_locals_dict=safe_locals_dict_to_use)

        # Stop if the value is unchanged
        if output_value == value:
            return value

        # Make a last evaluation to restore value type bool, int...
        try:
            final_eval_result = eval(output_value, {"__builtins__": None}, {})
        except (SyntaxError, NameError, TypeError):
            # Possibly the evaluate string is a final string at this step
            pass
        else:
            if type(final_eval_result) != tuple:  # "a, b" is considered as a tuple (a, b)
                output_value = final_eval_result

        return output_value

    def _replace_references_on_parameter_in_value(self, value: Union[str, int, float, bool, list, dict], dict_path: DictPath, path_based_dict: PathBasedDictionary, max_number_of_loop=10) -> Optional[Union[str, int, float, bool, list, dict]]:
        """
        Research the value of the parameter referenced by the pattern '${...}' and replace the pattern by the found value.
        If no value is found the function raise an UserWarning exception.
        The function makes several loops on the result to manage nested references.
        """
        if not isinstance(value, str):
            return value

        output_value = value
        loop_count = 0
        while loop_count < max_number_of_loop:
            loop_count += 1

            referenced_parameters = re.findall(r"\${((?:(?!\${).)*?)}", output_value, re.MULTILINE)
            if len(referenced_parameters) == 0:
                break

            for referenced_parameter in referenced_parameters:
                if "/" in referenced_parameter:
                    parameter_value, _, _ = self._search_by_deployment_path(referenced_parameter, dict_path, path_based_dict)
                else:
                    parameter_value, _, _ = self._search_from_here_to_the_top_of_the_parameter_value(referenced_parameter, dict_path, path_based_dict)
                if parameter_value is None:
                    raise UserWarning(f"The '{dict_path}' parameter reference '{referenced_parameter}' not found")
                output_value = output_value.replace(f"${{{referenced_parameter}}}", str(parameter_value))
        else:
            raise UserWarning(f"The '{dict_path}' replace reference not done before the max allowed loop")

        return output_value

    # noinspection GrazieInspection
    def _replace_references_on_lambdas_in_value(self, value: Union[str, int, float, bool, list, dict], dict_path: DictPath, path_based_dict: PathBasedDictionary, safe_globals_dict: dict = None, safe_locals_dict: dict = None, max_number_of_loop=10) -> Optional[Union[str, int, float, bool, list, dict]]:
        """
        Evaluate the expression referenced by the pattern '<<[parameter name],[parameter name]: [expression with a, b...]]>>'
        or '{[parameter name],[parameter name]= [expression with a, b...]}' and replace the pattern by the evaluation result.
        If ":" the result is only set in the return value.
        If "=" the result is set in the return value and in the first parameter reference.
        In case of evaluation failure, the function raise an UserWarning exception.
        The function makes several loops on the result to manage nested references.
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

            lambda_tuples = re.findall(r"<<([A-Za-z0-9.\-_, ]*)([:=]+?)([A-Za-z0-9.\-_+ \"'()\[\]:{}]*?)>>", output_value, re.MULTILINE)
            if len(lambda_tuples) == 0:
                break

            for lambda_tuple in lambda_tuples:
                if isinstance(lambda_tuple, tuple) and len(lambda_tuple) != 3:
                    raise UserWarning(f"Command '{lambda_tuple}' was unexpected")
                current_value = output_value
                parameters_name_string = lambda_tuple[0]
                parameters_name_tuple = lambda_tuple[0].split(",")
                result_destination = lambda_tuple[1]
                lambda_string = lambda_tuple[2]

                # Research the reference of the lambda parameters
                parameters_values = {}
                parameters_parent_dic = {}
                for parameter_name in parameters_name_tuple:
                    parameter_name = parameter_name.strip()
                    parameter_value, parameter_parent_dict, _ = self._search_from_here_to_the_top_of_the_parameter_value(parameter_name, dict_path, path_based_dict)
                    if parameter_value is None:
                        raise UserWarning(f"The '{dict_path}' parameter '{parameter_name}' not found")

                    parameters_values[parameter_name] = parameter_value
                    parameters_parent_dic[parameter_name] = parameter_parent_dict

                # Build the lambda arg as a, b, c...
                abc_string = ",".join(list(string.ascii_lowercase[:len(parameters_name_tuple)]))
                evaluation_string = f"lambda {abc_string}: {lambda_string}"

                # Evaluate the lambda expression
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
                    raise UserWarning(f"Evaluation ('''{evaluation_string}''') failed: {e}")

                # Apply the lambda function
                lambda_result = lambda_function(*parameters_values.values())

                # Affect or not the lambda function results
                if result_destination.startswith("="):
                    parameters_parent_dic[parameters_name_tuple[0].strip()][parameters_name_tuple[0].strip()] = lambda_result

                # Replace the lambda pattern for the following loop
                rebuilt_string = f"<<{parameters_name_string}{result_destination}{lambda_string}>>"
                output_value = current_value.replace(rebuilt_string, str(lambda_result))
                # make_final_evaluation = True
        else:
            raise UserWarning(f"The '{dict_path}' replace lambda not done before the max allowed loop")

        # if make_final_evaluation:
        #     try:
        #         final_eval_result = eval(output_value, {"__builtins__": None}, {})
        #     except (SyntaxError, NameError, TypeError):
        #         # Possibly the evaluate string is a final string at this step
        #         pass
        #     else:
        #         output_value = final_eval_result

        return output_value

    def _get_component_configuration_from_config_equinox_sh(self, component_name: str) -> Tuple[dict, dict]:
        component_equinox_source_file_path = self.componentConfigDirPath / component_name / "equinox.sh"

        opt_file_lines = []
        try:
            with component_equinox_source_file_path.open("r") as sh_file:
                for line in sh_file.readlines():
                    if line.lstrip().startswith("OPT_"):
                        opt_file_lines.append(line)
        except OSError as e:
            raise UserWarning(f"Read file '{component_equinox_source_file_path.relative_to(self.componentConfigDirPath)}' content failed: {e}")

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
                    print(f"     !! Check component parameter list from equinox, the ':' in define is missing in component '{component_name}' in line: {opt_line.strip()}")
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
                    print(f"     !! Check component parameter list from equinox, failed to get default info in component '{component_name}' in line: {opt_line.strip()}")
                    continue
                if component_parameter_name not in equinox_parameter_value_by_component_parameter_name:
                    equinox_parameter_value_by_component_parameter_name[component_parameter_name] = equinox_component_parameter_value
                    equinox_parameter_name_by_component_parameter_name[component_parameter_name] = equinox_parameter_name
                else:
                    print(f"     !! Check component parameter list from equinox, the parameter '{component_parameter_name}' is defined several time (by a new equinox parameter '{equinox_parameter_name}') in component '{component_name}' in line: {opt_line.strip()}")
                continue

            for component_parameter_name, equinox_parameter_name in equinox_parameter_name_by_component_parameter_name.items():
                pattern = f'OPT_{equinox_parameter_name}=["${{]*(?P<additional_equinox_parameter_value>[^ }}]*)'
                parameter_name_and_other_value_math = re.match(pattern, opt_line.strip())
                if parameter_name_and_other_value_math is None:
                    continue
                additional_equinox_parameter_value = parameter_name_and_other_value_math.group("additional_equinox_parameter_value").strip().strip('"')
                additional_equinox_parameter_value = additional_equinox_parameter_value.replace("${", "$!{")
                if additional_equinox_parameter_value is None:
                    print(f"     !! Check component parameter list from equinox, failed to get other info in component '{component_name}' in line: {opt_line.strip()}")
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
        Evaluate the expression referenced by the pattern '$<...>' and replace the pattern by the evaluation result.
        In case of evaluation failure, the function raise an UserWarning exception.
        The function makes several loops on the result to manage nested references.
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
                    raise UserWarning(f"Evaluation of '''{referenced_evaluation}''' failed: {e}")
                else:
                    output_value = output_value.replace(f"$<{referenced_evaluation}>", str(eval_result))
                    # make_final_evaluation = True
        else:
            raise UserWarning(f"The replace evaluation not done before the max allowed loop")

        # if make_final_evaluation:
        #     try:
        #         final_eval_result = eval(output_value, {"__builtins__": None}, {})
        #     except (SyntaxError, NameError, TypeError):
        #         # Possibly the evaluate string is a final string at this step
        #         pass
        #     else:
        #         output_value = final_eval_result

        return output_value


class DeploymentDescriptionDeployer(DeploymentDescriptionParser):
    runningDeploymentDescriptionJsonFileName = "running-deployment.json"
    runningDeploymentStatusKey = "deploymentRunningStatus"
    isDeployedKey = "isDeployed"
    isGanComponentsRunningKey = "isGanComponentsRunning"

    def __init__(self, deployment_folder_path: Path):
        DeploymentDescriptionParser.__init__(self)

        self.deploymentDirPath = deployment_folder_path
        self.runningDeploymentDescriptionJsonFile = self.deploymentDirPath / self.runningDeploymentDescriptionJsonFileName

    def _parse_the_deployment_description_json_file(self, deployment_description_json_file_path) -> NoReturn:
        self._deployment_dict = self._get_dict_from_json_file(deployment_description_json_file_path)
        self.parse_deployment_description_dict(self._deployment_dict)

    def _process_key_starting(self, new_key_in_the_path: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> Optional[str]:
        key_dict_path = dict_path.get_the_path_to_a_following_step(new_key_in_the_path)
        parent_path_step = dict_path.get_the_last_step_of_the_path()

        if parent_path_step == self.key_words["label_of_a_node_dictionary"]:
            self._node_deployment_starting(key_dict_path, path_based_dict)

        if new_key_in_the_path.startswith(self.key_words["label_of_a_components_group"]):
            self._process_component_group_starting(key_dict_path, path_based_dict)
        elif parent_path_step == self.key_words["label_of_a_component_dictionary"]:
            self._component_deployment_starting(key_dict_path, path_based_dict)

        return new_key_in_the_path

    def _process_key_ending(self, new_key_in_the_path: str, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        key_dict_path = dict_path.get_the_path_to_a_following_step(new_key_in_the_path)
        parent_path_step = dict_path.get_the_last_step_of_the_path()

        if parent_path_step == self.key_words["label_of_a_node_dictionary"]:
            self._node_deployment_ending(key_dict_path, path_based_dict)

        if new_key_in_the_path.startswith(self.key_words["label_of_a_components_group"]):
            self._component_group_deployment_ending(key_dict_path, path_based_dict)
        elif parent_path_step == self.key_words["label_of_a_component_dictionary"]:
            self._component_deployment_ending(key_dict_path, path_based_dict)

    def _process_final_value(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> bool:
        is_value_updated = False
        return is_value_updated

    def _node_deployment_starting(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        pass

    def _node_deployment_ending(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        pass

    def _process_component_group_starting(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        self._component_group_deployment_starting(dict_path, path_based_dict)

        component_group_dict = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path, default_value={})

        if self.key_words["label_of_a_database_dictionary"] in component_group_dict:
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
        database_description_dict = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path)

        database_host = database_description_dict.get(self.key_words["label_of_the_database_host"], None)
        if database_host is None:
            raise UserWarning(f"The '{dict_path}' database description doesn't defined its database host")

        database_port = database_description_dict.get(self.key_words["label_of_the_database_port"], None)
        if database_port is None:
            raise UserWarning(f"The '{dict_path}' database description doesn't defined its database port")

        return database_host, database_port

    def _get_container_group(self, container_name: str) -> str:
        return container_name.split("-")[1]

    def _get_from_here_to_the_top_of_the_dict_path_to_the_database_to_use(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> DictPath:
        _, _, database_to_use_dict_path = self._search_from_here_to_the_top_of_the_parameter_value(self.key_words["label_of_a_database_dictionary"], dict_path, path_based_dict)
        if database_to_use_dict_path is None:
            raise UserWarning(f"The database to use from the '{dict_path}' dictionary path is not found")
        return database_to_use_dict_path

    def _get_the_gan_project_name(self, path_based_dict: PathBasedDictionary) -> str:
        return path_based_dict.get_the_value_pointed_by_a_dict_path(DictPath(from_dict_path_as_list=[self.key_words["label_of_the_gan_project_name"]]))

    def _get_the_component_name_and_version(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> Tuple[str, str]:
        components_version = path_based_dict.get_the_value_pointed_by_a_dict_path(DictPath(from_dict_path_as_list=[self.key_words["label_of_the_gan_version"]]))
        component_description_dict = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path)
        component_description_name = component_description_dict.get(self.key_words["label_of_the_component_description_name"], None)
        component_name = component_description_dict.get(self.key_words["label_of_the_component_name"], None)
        if component_name is None:
            raise UserWarning(f"The component group '{dict_path}' doesn't defined '{component_description_name}' component name")
        return component_name, components_version

    def _get_the_component_environments_variables(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> dict:
        component_description_dict = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path)
        component_environment_variables_by_name = component_description_dict.get(self.key_words["label_of_a_component_env_var_dictionary"], {})
        component_environment_variables_by_name = {k: json.dumps(v) if not isinstance(v, str) else v for k, v in component_environment_variables_by_name.items() if not k.startswith("DEFAULT VALUE OF")}
        return component_environment_variables_by_name

    def _get_the_component_environments_variables_for_subprocess(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> dict:
        component_environment_variables_by_name = self._get_the_component_environments_variables(dict_path, path_based_dict)

        os_env = copy.deepcopy(os.environ)
        env_to_use = dict(os_env)
        env_to_use.update(component_environment_variables_by_name)

        return env_to_use

    def is_gan_components_deployed(self) -> bool:
        return self._get_running_status_from_running_deployment_dict(self.isDeployedKey, default_value=False)

    def is_gan_components_running(self) -> bool:
        return self._get_running_status_from_running_deployment_dict(self.isGanComponentsRunningKey, default_value=False)

    def _set_deployed_status(self, status_value: bool) -> NoReturn:
        self._set_running_status_to_running_deployment_dict(self.isDeployedKey, status_value)

    def _set_gan_components_running_status(self, status_value: bool) -> NoReturn:
        self._set_running_status_to_running_deployment_dict(self.isGanComponentsRunningKey, status_value)

    def _parse_the_running_deployment_dict(self) -> NoReturn:
        self._deployment_dict = self._get_dict_from_json_file(self.runningDeploymentDescriptionJsonFile)
        self.parse_deployment_description_dict(self._deployment_dict)

    def _read_the_running_deployment_dict(self) -> NoReturn:
        self._deployment_dict = self._get_dict_from_json_file(self.runningDeploymentDescriptionJsonFile)

    def _get_the_path_base_running_deployment_dict(self) -> NoReturn:
        self._read_the_running_deployment_dict()
        return PathBasedDictionary(self._deployment_dict)

    def _write_the_running_deployment_dict_to_json_file(self) -> NoReturn:
        self._write_dict_to_json_file(self._deployment_dict, self.runningDeploymentDescriptionJsonFile)

    def _set_running_status_to_running_deployment_dict(self, running_status_name: str, running_status_value: Any) -> NoReturn:
        self._deployment_dict.setdefault(self.runningDeploymentStatusKey, {})[running_status_name] = running_status_value
        self._write_the_running_deployment_dict_to_json_file()

    def _get_running_status_from_running_deployment_dict(self, running_status_name: str, default_value=None) -> Optional[Any]:
        if self._deployment_dict is not None:
            return self._deployment_dict.get(self.runningDeploymentStatusKey, {}).get(running_status_name, default_value)

        if not self.runningDeploymentDescriptionJsonFile.exists():
            return default_value

        self._deployment_dict = self._get_dict_from_json_file(self.runningDeploymentDescriptionJsonFile)
        status_value = self._deployment_dict.get(self.runningDeploymentStatusKey, {}).get(running_status_name, default_value)
        self._deployment_dict = None

        return status_value


class PelDeploymentDescriptionParser(DeploymentDescriptionDeployer):
    pelFolderName = "pel-target"
    runningDeploymentRootFolderName = "deployment"
    runningDeploymentDatabasesRootFolderName = "pg-data-root"
    runningDeploymentOriginalDatabasesRootFolderName = "pg-data-root-original"
    runningDeploymentLogFolderName = "logs"
    componentEquinoxShPid = "equinox-sh-pid"
    isComponentRunning = "isComponentRunning"
    launcherShLogFileName = "launcher-sh.log"
    equinoxShLogFileName = "equinox-sh.log"
    killEquinoxShLogFileName = "kill-equinox-sh.log"
    isSingleDslDeployedKey = "isSingleDslDeployed"
    isDatabasesRunningKey = "isDatabasesRunning"
    isSingleDslGanComponentsRunningKey = "isSingleDslGanComponentsRunningKey"
    isTestInProgressKey = "isTestInProgressKey"

    def __init__(self, deployment_folder_path: Path):
        self.pelDirPath = deployment_folder_path / self.pelFolderName

        DeploymentDescriptionDeployer.__init__(self, self.pelDirPath)

        self.runningDeploymentPath = self.pelDirPath / self.runningDeploymentRootFolderName
        self.databasesDirPath = self.pelDirPath / self.runningDeploymentDatabasesRootFolderName
        self.originalDatabasesDirPath = self.pelDirPath / self.runningDeploymentOriginalDatabasesRootFolderName
        self.logDirPath = self.pelDirPath / self.runningDeploymentLogFolderName

        self._deployment_dict = None

    def is_gan_components_single_dsl_deployed(self) -> bool:
        return self._get_running_status_from_running_deployment_dict(self.isSingleDslDeployedKey, default_value=False)

    def is_single_dsl_gan_components_running(self) -> bool:
        return self._get_running_status_from_running_deployment_dict(self.isSingleDslGanComponentsRunningKey, default_value=False)

    def is_databases_running(self) -> bool:
        return self._get_running_status_from_running_deployment_dict(self.isDatabasesRunningKey, default_value=False)

    def _get_the_component_deployment_name_and_path(self, dict_path: DictPath) -> Tuple[str, Path]:
        component_deployment_path = self._get_deployment_path(dict_path)
        component_deployment_name = "/".join(component_deployment_path)
        component_deployment_path = self.runningDeploymentPath.joinpath(*component_deployment_path)
        return component_deployment_name, component_deployment_path

    def _get_the_component_log_file_path(self, dict_path: DictPath) -> Path:
        component_deployment_path = self._get_deployment_path(dict_path)
        component_log_file_path = self.logDirPath.joinpath(*component_deployment_path)
        return component_log_file_path

    def _get_database_folder_path_host_and_port_from_description_dict_path(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> Tuple[Path, str, int]:
        database_host, database_port = self._get_database_host_and_port_from_description_dict_path(dict_path, path_based_dict)
        parent_group_dict_path = self._get_parent_component_group_dict_path(dict_path)
        parent_group_deployment_path = self._get_deployment_path(parent_group_dict_path)
        database_name = "-".join(parent_group_deployment_path + [str(database_port)])
        database_dir_path = self.databasesDirPath / database_name
        return database_dir_path, database_host, database_port

    def _set_single_dsl_deployed_status(self, status_value: bool) -> NoReturn:
        self._set_running_status_to_running_deployment_dict(self.isSingleDslDeployedKey, status_value)

    def _set_databases_running_status(self, status_value: bool) -> NoReturn:
        self._set_running_status_to_running_deployment_dict(self.isDatabasesRunningKey, status_value)

    def _set_single_dsl_gan_components_running_status(self, status_value: bool) -> NoReturn:
        self._set_running_status_to_running_deployment_dict(self.isSingleDslGanComponentsRunningKey, status_value)

    def _set_test_in_progress_status(self, status_value: bool) -> NoReturn:
        self._set_running_status_to_running_deployment_dict(self.isTestInProgressKey, status_value)

    def _get_test_in_progress_status(self) -> bool:
        return self._get_running_status_from_running_deployment_dict(self.isTestInProgressKey, default_value=False)


class PelDeployer(PelDeploymentDescriptionParser):

    def __init__(self, deployment_folder_path: Path, component_config_dir_path: Path, component_tgz_dir_path: Path):
        PelDeploymentDescriptionParser.__init__(self, deployment_folder_path)

        self.componentConfigDirPath = component_config_dir_path
        self.componentTgzDirPath = component_tgz_dir_path

        self._removeStartAndDockerLoopFromEquinoxSh = None

    def deploy_from_deployment_description_json_file(self, deployment_description_json_file_path: Path, remove_start_and_docker_loop_from_equinox_sh: bool = False) -> NoReturn:
        if self.is_gan_components_running():
            raise UserWarning(f"A deployment is running on the folder '{self.pelDirPath}', stop it before any deployment")

        self._removeStartAndDockerLoopFromEquinoxSh = remove_start_and_docker_loop_from_equinox_sh

        if self.pelDirPath.exists():
            print(f"     - Delete '{self.pelDirPath}'")
            shutil.rmtree(self.pelDirPath, ignore_errors=True)
        self.pelDirPath.mkdir(parents=True, exist_ok=True)

        if self.runningDeploymentPath.exists():
            print(f"     - Delete '{self.runningDeploymentPath}'")
            shutil.rmtree(self.runningDeploymentPath, ignore_errors=True)
        self.runningDeploymentPath.mkdir(parents=True, exist_ok=True)

        if self.logDirPath.exists():
            print(f"     - Delete '{self.logDirPath}'")
            shutil.rmtree(self.logDirPath, ignore_errors=True)
        self.logDirPath.mkdir(parents=True, exist_ok=True)

        self._parse_the_deployment_description_json_file(deployment_description_json_file_path)
        self._set_deployed_status(True)

    def _node_deployment_starting(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        node_name = dict_path.get_the_last_step_of_the_path()
        node_deployment_path = self.runningDeploymentPath.joinpath(*self._get_deployment_path(dict_path))

        print(f"     - Create '{node_name}' folder '{node_deployment_path.relative_to(self.deploymentDirPath)}'")
        if node_deployment_path.exists():
            shutil.rmtree(node_deployment_path, ignore_errors=True)
        node_deployment_path.mkdir(parents=True, exist_ok=True)

    def _component_group_deployment_starting(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        component_group_deployment_name = "/".join(self._get_deployment_path(dict_path))
        component_group_deployment_path = self.runningDeploymentPath.joinpath(*self._get_deployment_path(dict_path))

        print(f"         - Make a PEL deployment of the '{component_group_deployment_name}' component group in the folder '{component_group_deployment_path.relative_to(self.deploymentDirPath)}'")
        if component_group_deployment_path.exists():
            shutil.rmtree(component_group_deployment_path, ignore_errors=True)
        component_group_deployment_path.mkdir(parents=True, exist_ok=True)

    def _component_group_database_deployment(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        database_dir_path, _, database_port = self._get_database_folder_path_host_and_port_from_description_dict_path(dict_path, path_based_dict)

        if not DataBase.create_database(database_dir_path):
            raise UserWarning(f"The database '{database_dir_path.name}' creation failed")

        print(f"         - The database '{database_dir_path.name}' creation is done")

        if not DataBase.start_database(database_dir_path, database_port):
            raise UserWarning(f"The database '{database_dir_path.name}' start on port '{database_port}' failed")

        print(f"         - The database '{database_dir_path.name}' on port '{database_port}' is started")

        self._set_databases_running_status(True)

    def _component_deployment_starting(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        component_deployment_name, component_deployment_path = self._get_the_component_deployment_name_and_path(dict_path)
        subprocess_environment_variables = self._get_the_component_environments_variables_for_subprocess(dict_path, path_based_dict)
        component_name, components_version = self._get_the_component_name_and_version(dict_path, path_based_dict)
        gen_project_name = self._get_the_gan_project_name(path_based_dict)

        print(f"             - Create the '{component_deployment_name}' component in the folder'{component_deployment_path.relative_to(self.deploymentDirPath)}'")
        component_tgz_name = self._get_component_associated_tgz_name(component_name, components_version, gen_project_name)
        print(f"                 - Unarchive the component tgz associated file '{component_tgz_name}'")
        tgz_file_path = self.componentTgzDirPath / component_tgz_name
        if not tgz_file_path.exists() or not tarfile.is_tarfile(tgz_file_path):
            raise UserWarning(f"The component tgz file '{tgz_file_path.relative_to(self.componentTgzDirPath)}' doesn't exist or is not a tar file")
        try:
            with tarfile.open(tgz_file_path, "r:gz") as tar:
                tar.extractall(component_deployment_path)
        except (OSError, tarfile.TarError) as e:
            raise UserWarning(f"Extract tgz file '{tgz_file_path.relative_to(self.componentTgzDirPath)}' failed: {e}")

        component_equinox_source_file_path = self.componentConfigDirPath / component_name / "equinox.sh"
        component_equinox_destination_file_path = component_deployment_path / "equinox.sh"

        if self._removeStartAndDockerLoopFromEquinoxSh:
            print(f"                 - Copy a truncated version of the component associated script file '{component_equinox_source_file_path.relative_to(self.componentConfigDirPath)}'")
            sh_file_lines = []
            try:
                with component_equinox_source_file_path.open("r") as sh_file:
                    for line in sh_file.readlines():
                        # if not line.lstrip().startswith('exec "$@"'):
                        if not line.lstrip().startswith("./launcher.sh start"):
                            sh_file_lines.append(line)
                        else:
                            break
            except OSError as e:
                raise UserWarning(f"Load file '{component_equinox_source_file_path.relative_to(self.componentConfigDirPath)}' content failed: {e}")

            try:
                with component_equinox_destination_file_path.open("w", newline="\n") as sh_file:
                    sh_file.writelines(sh_file_lines)
                # Restore the file permissions
                os.chmod(component_equinox_destination_file_path, 0o777)
            except OSError as e:
                raise UserWarning(f"Write file '{component_equinox_destination_file_path.relative_to(self.deploymentDirPath)}' content failed: {e}")
        else:
            print(f"                 - Copy the component associated script file '{component_equinox_source_file_path.relative_to(self.componentConfigDirPath)}'")
            shutil.copy2(str(component_equinox_source_file_path), str(component_equinox_destination_file_path))

        print(f"                 - Run this script file '{component_equinox_destination_file_path.relative_to(self.deploymentDirPath)}'")
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

            print(f"                     - Detach process...")
            process = run_detach_subprocess(log_file_path, command_arguments, environment_variables=subprocess_environment_variables, current_working_directory=component_equinox_destination_file_path.parent)

            print(f"                     - Detach process pid: {process.pid}")
            path_based_dict.set_the_value_pointed_by_a_dict_path(process.pid, dict_path.get_the_path_to_a_following_step(self.componentEquinoxShPid))

            path_based_dict.set_the_value_pointed_by_a_dict_path(True, dict_path.get_the_path_to_a_following_step(self.isComponentRunning))

    @staticmethod
    def _get_component_associated_tgz_name(component_name: str, gan_version: str, gan_project_name) -> str:
        return f"{gan_project_name}-{gan_version}-{component_name}.tar.gz"


class PelRunning(PelDeploymentDescriptionParser):

    def __init__(self, deployment_folder_path: Path):
        PelDeploymentDescriptionParser.__init__(self, deployment_folder_path)
        self._singleDslPel = SingleDslPel(deployment_folder_path)
        self._actionToBePerformed = None
        self._runningComponentsCount = None

    def start(self, component_deployment_path: str = None) -> NoReturn:
        if not self.is_gan_components_deployed():
            print(" - The gan components are not deployed")
            return

        if component_deployment_path is not None:
            if self.is_single_dsl_gan_components_running():
                print(" - Not available while a single DSL deployment is running")
            else:
                self._perform_the_action_on_one_component(component_deployment_path, "start")
                self._set_gan_components_running_status(True)
        else:
            if self.is_databases_running():
                print(" - Databases are already running")
            else:
                self._perform_the_action("start-databases")

                print(" - Pause for 30s to let the databases start...")
                time.sleep(30)

            if self.is_gan_components_running():
                print(" - Gan components are already running")
            else:
                if self.logDirPath.exists():
                    shutil.rmtree(self.logDirPath, ignore_errors=True)
                self.logDirPath.mkdir(parents=True, exist_ok=True)

                self._perform_the_action("start")
                self._set_gan_components_running_status(True)

    def stop(self, component_deployment_path: str = None) -> NoReturn:
        if self.is_single_dsl_gan_components_running():
            print(" - Not available while a single DSL deployment is running")
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
                print(" - No database to stop")

            if not self.is_gan_components_running():
                print(" - No gan components to stop")
            else:
                self._perform_the_action("stop")
                self._set_gan_components_running_status(False)

    def _count_the_running_components(self) -> int:
        self._runningComponentsCount = 0
        self._actionToBePerformed = "countRunning"
        self._parse_the_running_deployment_dict()
        return self._runningComponentsCount

    def _get_components_path_in_description_order(self) -> List[Path]:
        self._componentsPathInDescriptionOrder = []
        self._actionToBePerformed = "getComponentsPath"
        self._parse_the_running_deployment_dict()
        return self._componentsPathInDescriptionOrder

    def _perform_the_action(self, action: str) -> NoReturn:
        self._actionToBePerformed = action

        self._parse_the_running_deployment_dict()
        self._write_the_running_deployment_dict_to_json_file()

    def _perform_the_action_on_one_component(self, component_deployment_path: str, action: str) -> NoReturn:
        self._actionToBePerformed = action

        if not self.logDirPath.exists():
            self.logDirPath.mkdir(parents=True, exist_ok=True)

        path_base_dict = self._get_the_path_base_running_deployment_dict()
        _, _, dict_path = self._search_by_deployment_path(component_deployment_path, DictPath(), path_base_dict)
        if dict_path is None:
            print(f" ! Component '{component_deployment_path}' {action} failed, the path target is not found")
            return

        if dict_path.get_the_path_to_parent().get_the_last_step_of_the_path() != self.key_words["label_of_a_component_dictionary"]:
            print(f" ! Component '{component_deployment_path}' {action} failed, the path target is not a component")
            return

        self._component_deployment_starting(dict_path, path_base_dict)
        self._write_the_running_deployment_dict_to_json_file()

    def _component_group_database_deployment(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        if self._actionToBePerformed == "start-databases":
            database_dir_path, _, database_port = self._get_database_folder_path_host_and_port_from_description_dict_path(dict_path, path_based_dict)

            if not DataBase.start_database(database_dir_path, database_port):
                print(f"     - The database '{database_dir_path.name}' start failed")
            else:
                print(f"     - The database '{database_dir_path.name}' is started")

            self._set_databases_running_status(True)
        elif self._actionToBePerformed == "stop-databases":
            database_dir_path, _, database_port = self._get_database_folder_path_host_and_port_from_description_dict_path(dict_path, path_based_dict)

            if not DataBase.stop_database(database_dir_path):
                print(f"     - The database '{database_dir_path.name}' stop failed")
            else:
                print(f"     - The database '{database_dir_path.name}' is stopped")

    # noinspection PyUnusedLocal
    def _component_deployment_starting(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
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
            print(f"     - The component '{component_deployment_name}' is already started")
            return

        if not is_component_running and self._actionToBePerformed == "stop":
            print(f"     - The component '{component_deployment_name}' is already stopped")
            return

        component_equinox_sh_pid_dict_path = dict_path.get_the_path_to_a_following_step(self.componentEquinoxShPid)
        component_equinox_sh_pid = path_based_dict.get_the_value_pointed_by_a_dict_path(component_equinox_sh_pid_dict_path, default_value=None)
        component_launcher_file_path = component_deployment_path / "launcher.sh"

        if self._actionToBePerformed == "getComponentsPath":
            self._componentsPathInDescriptionOrder.append(component_deployment_path)
            return

        print(f"     - {self._actionToBePerformed.capitalize()} the component '{component_deployment_name}', so run this script file '{component_launcher_file_path.name} {self._actionToBePerformed}'")
        command_arguments = ["./" + component_launcher_file_path.name, self._actionToBePerformed]
        command_arguments = adapt_the_command_arguments_when_using_bash_on_windows(command_arguments)

        log_file_path = self._get_the_component_log_file_path(dict_path) / f"{self._actionToBePerformed}-{self.launcherShLogFileName}"
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        complete_process = run_subprocess(log_file_path, command_arguments, environment_variables=subprocess_environment_variables, current_working_directory=component_launcher_file_path.parent)
        if complete_process.returncode != 0:
            print(f"        ! {self._actionToBePerformed.capitalize()} the component '{component_deployment_name}' failed")
        else:
            path_based_dict.set_the_value_pointed_by_a_dict_path(self._actionToBePerformed == "start", dict_path.get_the_path_to_a_following_step(self.isComponentRunning))

        if self._actionToBePerformed == "stop":
            if component_equinox_sh_pid is not None:
                print(f"     - Kill the '{dict_path}' component equinox.sh process pid {component_equinox_sh_pid}")
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
                print(f"     - Copy the '{component_deployment_name}' component logs to '{log_file_dir_path.relative_to(self.logDirPath)}'")
                copy_tree(str(component_deployment_path / "logs"), str(log_file_dir_path), preserve_mode=True)

    def build_single_dsl_pel(self, dsl_log_xml_trace_level: str = "DEBUG", dsl_log_xml_max_log_file_size: int = 10240000):
        if not self.is_gan_components_deployed():
            print(" - The gan components are not deployed")
            return

        if self.is_gan_components_running():
            print(" - Gan components are running, so stop them before to attempt to build a single DSL PEL")
            return

        ordered_dsl_paths = self._get_components_path_in_description_order()

        self._read_the_running_deployment_dict()
        self._singleDslPel.build_single_dsl_pel_deployment(dsl_log_xml_trace_level, dsl_log_xml_max_log_file_size, ordered_dsl_paths)
        self._set_single_dsl_deployed_status(True)

    def start_single_dsl_pel(self):
        if not self.is_gan_components_single_dsl_deployed():
            print(" - The gan components are not deployed as single DSL")
            return

        if self.is_databases_running():
            print(" - Databases are already running")
        else:
            self._perform_the_action("start-databases")

            print(" - Pause for 30s to let the databases start...")
            time.sleep(30)

        if self.is_gan_components_running():
            print(" - Gan components are already running")
        else:
            self._read_the_running_deployment_dict()
            self._singleDslPel.start_single_dsl()
            self._set_gan_components_running_status(True)
            self._set_single_dsl_gan_components_running_status(True)

    def stop_single_dsl_pel(self):
        if not self.is_single_dsl_gan_components_running():
            print(" - Not available while a no single DSL PEL deployment is running")
            return

        if self.is_databases_running():
            self._perform_the_action("stop-databases")
            self._set_databases_running_status(False)
        else:
            print(" - No database to stop")

        if not self.is_gan_components_running():
            print(" - No gan components to stop")
        else:
            self._read_the_running_deployment_dict()
            self._singleDslPel.stop_single_dsl()
            self._set_gan_components_running_status(False)
            self._set_single_dsl_gan_components_running_status(False)

    def copy_working_databases_data_root_folder_as_original(self) -> NoReturn:
        if self.is_databases_running():
            print("Databases are running, so impossible to make the original copy")
            return

        if not DataBase.save_databases_data_folders(self.databasesDirPath, self.originalDatabasesDirPath):
            print(f"The working databases data folders copy failed")
        else:
            print(f"The working databases data folders are saved as original")

    def restore_working_databases_data_root_folder_from_original(self) -> NoReturn:
        if self.is_databases_running():
            print("Databases are running, so impossible to restore the original")
            return

        if not DataBase.restore_databases_data_folders(self.originalDatabasesDirPath, self.databasesDirPath):
            print(f"The working databases data folders restoration failed")
        else:
            print(f"The working databases data folders are restored")

    def test(self, cataclysm_folder_path: Path, test_profile: str, test_name_to_run: str = None) -> NoReturn:
        if not self.is_databases_running():
            print(" - Databases are not running")
            return

        if not self.is_gan_components_running():
            print(" - Gan components are not running")
            return

        print(f" - Test the deployment in the folder '{self.runningDeploymentPath}'")

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
        print(f"    - Create database on '{database_data_dir_path}' data folder...")

        print(f"        - Delete if existing and create the '{database_data_dir_path}' database folder...")
        if database_data_dir_path.exists():
            shutil.rmtree(database_data_dir_path, ignore_errors=True)
        database_data_dir_path.mkdir(parents=True, exist_ok=True)

        if platform.system() != "Windows" and os.geteuid() == 0:
            # noinspection PyArgumentList
            complete_process = subprocess.run(["chown", "postgres:postgres", "-R", str(database_data_dir_path)],
                                              cwd=None, text=True, capture_output=True)
            if complete_process.returncode != 0:
                print(f"Set owner 'postgres:postgres' to folder'{database_data_dir_path}' failed")
                return False
            else:
                print(f"Set owner 'postgres:postgres' to folder'{database_data_dir_path}' successful")

        print(f"        - Init postgresql database on '{database_data_dir_path}' data folder...")
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
            print(f"    ! Init database on '{database_data_dir_path}' data folder return failed code {complete_process.returncode}: {complete_process.stderr} - {complete_process.stdout}")
            return False

        print(f"        - Update database 'pg_hba.conf'...")
        pg_hba_conf_file_path = database_data_dir_path / "pg_hba.conf"

        shutil.copy2(str(pg_hba_conf_file_path), str(pg_hba_conf_file_path) + ".backup")

        is_ipv4_local_connections_line = False
        is_ipv6_local_connections_line = False

        try:
            with pg_hba_conf_file_path.open("r") as psql_cfg_file:
                pg_hba_conf_file_lines = psql_cfg_file.readlines()
        except OSError as e:
            raise UserWarning(f"Read file '{pg_hba_conf_file_path}' content failed: {e}")

        new_pg_hba_conf_file_lines = []
        for line in pg_hba_conf_file_lines:
            line = line.rstrip("\n")
            line = line.rstrip("\r")
            # noinspection GrazieInspection
            if is_ipv4_local_connections_line:
                #                                  host    all             all             127.0.0.1/32            trust
                new_pg_hba_conf_file_lines.append("host    all             all             all                     trust\n")
                is_ipv4_local_connections_line = False
                continue
            elif is_ipv6_local_connections_line:
                #                                  host    all             all             ::1/128                 trust
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
            raise UserWarning(f"Write file '{pg_hba_conf_file_path}' content failed: {e}")

        print(f"        - Update database 'postgresql.conf' for '{platform.system()}' platform system...")
        postgresql_conf_file_path = database_data_dir_path / "postgresql.conf"

        shutil.copy2(str(postgresql_conf_file_path), str(postgresql_conf_file_path) + ".backup")

        is_windows = (platform.system() == "Windows")

        try:
            with postgresql_conf_file_path.open("r") as psql_cfg_file:
                postgres_conf_file_lines = psql_cfg_file.readlines()
        except OSError as e:
            raise UserWarning(f"Read file '{postgresql_conf_file_path}' content failed: {e}")

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
            raise UserWarning(f"Write file '{postgresql_conf_file_path}' content failed: {e}")

        print(f"        - Create database on '{database_data_dir_path}' data folder done")
        return True

    @staticmethod
    def start_database(database_data_dir_path: Path, database_port: int) -> bool:
        print(f"Attempt to start database on port {database_port} and data folder'{database_data_dir_path}'...")
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
            # noinspection PyArgumentList
            complete_process = subprocess.run(command_arguments, user="postgres")
        else:
            complete_process = subprocess.run(command_arguments)
        if complete_process.returncode != 0:
            print(f"Start database on port {database_port} and data folder'{database_data_dir_path}' failed")
            return False
        else:
            print(f"Start database on port {database_port} and data folder'{database_data_dir_path}' successful")

        return True

    @staticmethod
    def stop_database(database_data_dir_path: Path) -> bool:
        print(f"Attempt to stop database on data folder'{database_data_dir_path}'...")
        command_arguments = ["pg_ctl", "-s", "-w", "-D", f"{database_data_dir_path}", "stop"]
        if platform.system() != "Windows" and os.geteuid() == 0:
            # noinspection PyArgumentList
            complete_process = subprocess.run(command_arguments, user="postgres", cwd=None, text=True, capture_output=True)
        else:
            complete_process = subprocess.run(command_arguments, cwd=None, text=True, capture_output=True)
        if complete_process.returncode != 0:
            print(f"Stop database on data folder'{database_data_dir_path}' failed: {complete_process.stderr} - {complete_process.stdout}")
            return False
        else:
            print(f"Stop database on data folder'{database_data_dir_path}' successful")
        return True

    @staticmethod
    def save_databases_data_folders(databases_working_root_dir_path: Path, databases_original_root_dir_path: Path) -> bool:
        if not databases_working_root_dir_path.exists():
            print(f"The working folder '{databases_working_root_dir_path}' doesn't exist")
            return False

        if databases_original_root_dir_path.exists():
            print(f"Delete exiting '{databases_original_root_dir_path}'")
            shutil.rmtree(databases_original_root_dir_path, ignore_errors=True)

        print(f"Copy the '{databases_working_root_dir_path}' working folder to '{databases_original_root_dir_path}'")
        shutil.copytree(str(databases_working_root_dir_path), str(databases_original_root_dir_path))

        return True

    @staticmethod
    def restore_databases_data_folders(databases_original_root_dir_path: Path, databases_working_root_dir_path: Path) -> bool:
        print(f"Init '{databases_working_root_dir_path}' databases data folder...")

        if not databases_original_root_dir_path.exists():
            print(f"The original folder '{databases_original_root_dir_path}' doesn't exist")
            return False

        if databases_working_root_dir_path.exists():
            print(f"Delete exiting '{databases_working_root_dir_path}'")
            shutil.rmtree(databases_working_root_dir_path, ignore_errors=True)

        print(f"Copy the original folder '{databases_original_root_dir_path}' to '{databases_working_root_dir_path}'")
        shutil.copytree(str(databases_original_root_dir_path), str(databases_working_root_dir_path))

        if platform.system() != "Windows" and os.geteuid() == 0:
            print(f"Attempt to set permission '0700' to folder'{databases_working_root_dir_path}'...")
            # noinspection PyArgumentList
            complete_process = subprocess.run(["chmod", "0700", "-R", str(databases_working_root_dir_path)], cwd=None,
                                              text=True, capture_output=True)
            if complete_process.returncode != 0:
                print(f"Set permission '0700' to folder'{databases_working_root_dir_path}' failed")
                return False
            else:
                print(f"Set permission '0700' to folder'{databases_working_root_dir_path}' successful")

            print(f"Attempt to set owner 'postgres:postgres' to folder'{databases_working_root_dir_path}'...")
            # noinspection PyArgumentList
            complete_process = subprocess.run(["chown", "postgres:postgres", "-R", str(databases_working_root_dir_path)],
                                              cwd=None, text=True, capture_output=True)
            if complete_process.returncode != 0:
                print(f"Set owner 'postgres:postgres' to folder'{databases_working_root_dir_path}' failed")
                return False
            else:
                print(f"Set owner 'postgres:postgres' to folder'{databases_working_root_dir_path}' successful")

        print(f"The '{databases_working_root_dir_path}' DBs data folder is initialised")
        return True


class SingleDslPel:
    singleDslPelDeploymentRootFolderName = "single-dsl-pel-deployment"
    consoleSingleDslLogFileName = "single-dsl-console.log"
    singleDslLogFolderName = "single-dsl-logs"

    def __init__(self, deployment_folder_path: Path):
        self.allDslRootDirPath = deployment_folder_path / PelDeploymentDescriptionParser.pelFolderName / PelDeploymentDescriptionParser.runningDeploymentRootFolderName
        self.singleDslTargetDirPath = deployment_folder_path / PelDeploymentDescriptionParser.pelFolderName / self.singleDslPelDeploymentRootFolderName
        self.logDirPath = deployment_folder_path / PelDeploymentDescriptionParser.pelFolderName / PelDeploymentDescriptionParser.runningDeploymentLogFolderName
        self.singleDslLogFolderPath = self.logDirPath / self.singleDslLogFolderName

    # noinspection GrazieInspection
    def build_single_dsl_pel_deployment(self, dsl_log_xml_trace_level: str = "DEBUG", dsl_log_xml_max_log_file_size: int = 10240000,
                                        ordered_dsl_paths: List[Path] = None) -> bool:
        if not self.allDslRootDirPath.is_dir():
            raise UserWarning(f"The PEL deployment folder '{self.allDslRootDirPath}' doesn't exist !")

        if self.singleDslTargetDirPath.exists():
            print(f"Delete exiting '{self.singleDslTargetDirPath}'")
            shutil.rmtree(self.singleDslTargetDirPath, ignore_errors=True)
        self.singleDslTargetDirPath.mkdir(parents=True, exist_ok=True)

        self.logDirPath.mkdir(parents=True, exist_ok=True)

        # List the DSLs
        if ordered_dsl_paths is None:
            dsl_paths = self.list_the_dsl_in_folder()
        else:
            dsl_paths = ordered_dsl_paths

        # Merge the jar files from "bin" DSLs folders into one folder
        self._merge_the_jar_files_from_dsl_folders_into_one_folder("bin", dsl_paths)

        # Merge the jar files from "lib" DSLs folders into one folder
        self._merge_the_jar_files_from_dsl_folders_into_one_folder("lib", dsl_paths)

        # Merge the resources files from "resources" DSLs folders into one folder
        self._merge_the_resources_files_from_dsl_folders_into_one_folder("resources", dsl_paths)

        # Merge the resources file store in DSLs definition folder
        self._merge_the_files_other_than_the_dsl_definition_files_from_dsl_folders_into_one_folder(["dsl.json", dsl_log_file], "etc", dsl_paths)

        # Merge the dsl.json files from "etc" DSLs folders into one file
        single_dsl_json_file_path, special_dsl_json_file_path_list = self._merge_the_dsl_json_file_from_dsl_folders_into_one_file("dsl.json", "etc", dsl_paths)
        if single_dsl_json_file_path is None:
            print(f"   ERROR: impossible to make the DLS json file, so abort !")
            return False

        # Build the single DSL dsl.log4j.xml file from the single DSL dsl.json file
        if not self._build_the_single_dsl_log_xml_file_from_the_single_dsl_json_file(dsl_log_file,
                                                                                     single_dsl_json_file_path,
                                                                                     trace_level=dsl_log_xml_trace_level,
                                                                                     max_log_file_size=dsl_log_xml_max_log_file_size):
            print(f"   ERROR: impossible to build the DLS log4j.xml file, so abort !")
            return False

        for special_dsl_json_file_path in special_dsl_json_file_path_list:
            # Build the single DSL dsl.log4j.xml file from the single DSL dsl.json file
            if not self._build_the_single_dsl_log_xml_file_from_the_single_dsl_json_file(dsl_log_file,
                                                                                         special_dsl_json_file_path,
                                                                                         trace_level=dsl_log_xml_trace_level,
                                                                                         max_log_file_size=dsl_log_xml_max_log_file_size):
                print(f"   ERROR: impossible to build the DLS log4j.xml file, so abort !")
                return False

            # Copy the others folder
            single_dsl_folder_path = single_dsl_json_file_path.parent.parent
            special_dsl_folder_path = special_dsl_json_file_path.parent.parent
            shutil.copytree(str(single_dsl_folder_path / "bin"), str(special_dsl_folder_path / "bin"))
            shutil.copytree(str(single_dsl_folder_path / "lib"), str(special_dsl_folder_path / "lib"))
            shutil.copytree(str(single_dsl_folder_path / "resources"), str(special_dsl_folder_path / "resources"))

        return True

    def start_single_dsl(self) -> bool:
        if not self.start_dsl(self.singleDslTargetDirPath / "main-dsl-folder"):
            return True

        has_some_failures = False
        single_dsl_folders = self.singleDslTargetDirPath.glob(f"*dsl-folder*")
        for single_dsl_folder in single_dsl_folders:
            if single_dsl_folder.name == "main-dsl-folder":
                continue

            if not self.start_dsl(single_dsl_folder, xms_option_value="64m", xmx_option_value="256m"):
                has_some_failures = True
        return has_some_failures

    def start_dsl(self, dsl_folder_path: Path, xms_option_value: str = None, xmx_option_value: str = None) -> bool:
        print(f"Start '{dsl_folder_path}' DSL...")

        dsl_bin_dir_path = dsl_folder_path / "bin"
        results = list(dsl_bin_dir_path.glob("dsl-*.jar"))
        if len(results) != 1:
            print(f"    ! Cannot find a single corresponding jar to dsl component in folder '{dsl_bin_dir_path}'")
            return False

        dsl_jar_path = results[0]

        command_arguments = [
            r"java",
            f"-Dname={dsl_folder_path.stem}",
            r"-Djava.security.egd=file:/dev/urandom",
            r"-Dvertx.logger-delegate-factory-class-name=io.vertx.core.logging.SLF4JLogDelegateFactory",
        ]

        if xms_option_value is not None:
            print(f"    '{dsl_bin_dir_path}' start with option '-Xms{xms_option_value}'")
            command_arguments += [f"-Xms{xms_option_value}"]

        if xmx_option_value is not None:
            print(f"    '{dsl_bin_dir_path}' start with option '-Xmx{xmx_option_value}'")
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
            print(f"    - Detach process...")
            process = run_detach_subprocess(dsl_log_file_path, command_arguments, current_working_directory=dsl_folder_path)
            print(f"    - Detach process pid: {process.pid}")

        print(f"The '{dsl_folder_path}' DSL was launched")
        return True

    def stop_single_dsl(self) -> bool:
        has_some_failures = False
        single_dsl_folders = self.singleDslTargetDirPath.glob(f"*dsl-folder*")
        for single_dsl_folder in single_dsl_folders:
            if not self.stop_dsl(single_dsl_folder):
                has_some_failures = True
        return has_some_failures

    def stop_dsl(self, dsl_folder_path: Path) -> bool:
        import requests

        print(f"Stop '{dsl_folder_path}' DSL...")

        dsl_conf_path = dsl_folder_path / "etc" / "dsl.json"
        try:
            with dsl_conf_path.open("r") as json_file:
                dsl_conf_dict = json.load(json_file)
        except (OSError, json.JSONDecodeError) as e:
            print(f"    ! Load json from file '{dsl_conf_path}' failed: ", e)
            return False

        if not isinstance(dsl_conf_dict, dict):
            print(f"    ! Json from file '{dsl_conf_path}' is not a dict ({dsl_conf_dict})")
            return False

        dsl_host = dsl_conf_dict.get("dsl.host", None)
        dsl_port = dsl_conf_dict.get("dsl.port", None)

        if dsl_host is None or dsl_port is None:
            print(f"    ! Impossible to get correct dsl host or port in dict ({dsl_conf_dict})")
            return False

        print(f"    - Attempt to post on url 'http://{dsl_host}:{dsl_port}/api/v1/stop'...")
        try:
            r = requests.post(f"http://{dsl_host}:{dsl_port}/api/v1/stop", json=None)
        except requests.exceptions.RequestException as e:
            print(f"Send post request failed:", e)
        else:
            if r.status_code == requests.codes.ok:
                print(f"    - Post request successful: {r.status_code}")
            else:
                print(f"    - Post request failed: {r.status_code}")
                # TODO: kill the process ?

        print(f"     - Copy the single DSL logs to '{self.singleDslLogFolderPath}'")
        single_dsl_logs_folder_path = dsl_folder_path / "logs"
        single_dsl_log_files_path = list(single_dsl_logs_folder_path.glob(f"**/*.log"))
        for single_dsl_log_file_path in single_dsl_log_files_path:
            log_file_name_parts = single_dsl_log_file_path.name.split("..")
            target_log_file_path = self.singleDslLogFolderPath.joinpath(*log_file_name_parts)
            print(f"         - Copy the single DSL log file '{single_dsl_log_file_path}' to '{target_log_file_path}'")
            target_log_file_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(str(single_dsl_log_file_path), str(target_log_file_path))
            except OSError as e:
                print(f"             ! Copy failed: {e}")

        return True

    @staticmethod
    def check_dsl_folder_is_complete(dsl_dir_path: Path) -> bool:
        is_complete = (dsl_dir_path / "etc" / "dsl.json").is_file()
        is_complete &= (dsl_dir_path / "etc" / dsl_log_file).is_file()
        is_complete &= (dsl_dir_path / "bin").is_dir()
        is_complete &= (dsl_dir_path / "lib").is_dir()
        return is_complete

    def list_the_dsl_in_folder(self) -> List[Path]:
        bin_folder_parent_results = sorted([p.parent for p in list(self.allDslRootDirPath.glob(f"**/bin")) if p.is_dir()])
        dsl_results = [p for p in bin_folder_parent_results if self.check_dsl_folder_is_complete(p)]
        print(f"- DSL folders in the root folder of the DSLs:")
        for result_path in dsl_results:
            print(f"    - {result_path.relative_to(self.allDslRootDirPath)}")
        return dsl_results

    def _merge_the_jar_files_from_dsl_folders_into_one_folder(self, jar_files_folder_name: str, dsl_dir_paths: List[Path]) -> NoReturn:
        # Create the target folder
        jar_files_target_dir_path = self.singleDslTargetDirPath / "main-dsl-folder" / jar_files_folder_name
        print(f"- Create the jar files target folder '{jar_files_target_dir_path}'")
        jar_files_target_dir_path.mkdir(parents=True, exist_ok=True)

        # Merge files
        print(f"- Merge the jar files from each 'DSL/{jar_files_folder_name}' into the target '{jar_files_folder_name}'")
        exiting_jar_full_names: List[str] = []
        exiting_jar_versions_by_name: Dict[str, List[str]] = {}
        for dsl_dir_path in dsl_dir_paths:
            jar_path_results: List[Path] = list((dsl_dir_path / jar_files_folder_name).glob(f"./*.jar"))
            for jar_path in jar_path_results:
                jar_full_name = jar_path.name

                if jar_full_name not in exiting_jar_full_names:
                    # Memorize the jar full name
                    exiting_jar_full_names.append(jar_full_name)

                    # Copy the jar file into the target folder
                    shutil.copy2(str(jar_path), str(jar_files_target_dir_path))

                    # Get the jar name and version
                    jar_nam_and_version_pattern = "^(?P<jar_name>(?:(?!-\d).)*)(-(?P<jar_version>\d+(?:(?!\.jar)\.\w+)*(?:-SNAPSHOT)*)|(\.jar))"
                    jar_name_and_version_math = re.match(jar_nam_and_version_pattern, jar_full_name)
                    if jar_name_and_version_math is None:
                        print(f"   ERROR: impossible to get name and version of the jar '{jar_path.relative_to(self.allDslRootDirPath)}' ! So no supplementary checks...")
                        continue

                    jar_name = jar_name_and_version_math.group("jar_name")
                    jar_version = jar_name_and_version_math.group("jar_version")
                    if jar_name is None:
                        print(f"   ERROR: impossible to get name of the jar '{jar_path.relative_to(self.allDslRootDirPath)}' ! So no supplementary checks...")
                        continue

                    if jar_version is None:
                        jar_version = "not defined"

                    # Check if there is a SNAPSHOT in the jar version
                    if isinstance(jar_version, str) and "SNAPSHOT" in jar_version:
                        print(f"   WARNING: the jar '{jar_path.relative_to(self.allDslRootDirPath)}' is in SNAPSHOT version !")

                    # Check if there is already the jar in another version
                    if jar_name in exiting_jar_versions_by_name.keys():
                        print(f"   WARNING: the jar '{jar_path.relative_to(self.allDslRootDirPath)}' is present in another version !")

                    # Memorize the jar version by its name
                    exiting_jar_versions_by_name.setdefault(jar_name, []).append(jar_version)

        # for jar_full_name in exiting_jar_full_names:
        #     print(f"    - The '{jar_full_name}' was copied to the target '{jar_files_folder_name}'")

        print(f"    - Resume of the used '{jar_files_folder_name}' versions of jar files by jar file name:")
        for jar_name, jar_versions in exiting_jar_versions_by_name.items():
            print(f"        - '{jar_name}' with the versions: {jar_versions}")

    def _merge_the_resources_files_from_dsl_folders_into_one_folder(self, resources_files_folder_name: str,
                                                                    dsl_dir_paths: List[Path]) -> NoReturn:
        # Create the target folder
        resources_files_target_dir_path = self.singleDslTargetDirPath / "main-dsl-folder" / resources_files_folder_name
        print(f"- Create the resources files target folder '{resources_files_target_dir_path}'")
        resources_files_target_dir_path.mkdir(parents=True, exist_ok=True)

        # Merge files
        print(f"- Merge the resources files from each 'DSL/{resources_files_folder_name}' folder into the target '{resources_files_folder_name}'")
        exiting_resource_relative_paths: List[Path] = []
        for dsl_dir_path in dsl_dir_paths:
            resource_file_path_results: List[Path] = [p for p in list((dsl_dir_path / resources_files_folder_name).glob(f"**/*"))if p.is_file()]
            for resource_path in resource_file_path_results:
                resource_relative_path = resource_path.relative_to(dsl_dir_path / resources_files_folder_name)

                if resource_relative_path not in exiting_resource_relative_paths:
                    # Memorize the resource relative path
                    exiting_resource_relative_paths.append(resource_relative_path)

                    # Copy the resource file into the target folder
                    resource_file_target_dir_path = resources_files_target_dir_path / resource_relative_path.parent
                    if not resource_file_target_dir_path.exists():
                        print(f"    - Create the resources folder '{resource_file_target_dir_path.relative_to(self.singleDslTargetDirPath)}'")
                        resource_file_target_dir_path.mkdir(parents=True, exist_ok=True)
                    print(f"    - Copy '{resource_path.relative_to(self.allDslRootDirPath)}' file to target folder"
                          f" '{resource_file_target_dir_path.relative_to(self.singleDslTargetDirPath)}'")
                    shutil.copy2(str(resource_path), str(resource_file_target_dir_path))

    def _merge_the_files_other_than_the_dsl_definition_files_from_dsl_folders_into_one_folder(self, dsl_definition_file_names: List[str],
                                                                                              dsl_definition_files_folder_name: str,
                                                                                              dsl_dir_paths: List[Path]) -> NoReturn:
        # Create the target folder
        resources_files_target_dir_path = self.singleDslTargetDirPath / "main-dsl-folder" / dsl_definition_files_folder_name
        print(f"- Create the DSL definition files target folder '{dsl_definition_files_folder_name}'")
        resources_files_target_dir_path.mkdir(parents=True, exist_ok=True)

        # Merge files
        print(f"- Merge the resources files from each 'DSL/{dsl_definition_files_folder_name}' folder into the target '{resources_files_target_dir_path}'")
        exiting_resource_relative_paths: List[Path] = []
        for dsl_dir_path in dsl_dir_paths:
            resource_file_path_results: List[Path] = [p for p in list(
                (dsl_dir_path / dsl_definition_files_folder_name).glob(f"**/*")) if
                                                      p.is_file() and p.name not in dsl_definition_file_names]
            for resource_path in resource_file_path_results:
                resource_relative_path = resource_path.relative_to(dsl_dir_path / dsl_definition_files_folder_name)

                if resource_relative_path not in exiting_resource_relative_paths:
                    # Memorize the resource relative path
                    exiting_resource_relative_paths.append(resource_relative_path)

                    # Copy the resource file into the target folder
                    resource_file_target_dir_path = resources_files_target_dir_path / resource_relative_path.parent
                    if not resource_file_target_dir_path.exists():
                        print(f"    - Create the resources folder '{resource_file_target_dir_path.relative_to(self.singleDslTargetDirPath)}'")
                        resource_file_target_dir_path.mkdir(parents=True, exist_ok=True)
                    print(f"    - Copy '{resource_path.relative_to(self.allDslRootDirPath)}' file to target folder"
                          f" '{resource_file_target_dir_path.relative_to(self.singleDslTargetDirPath)}'")
                    shutil.copy2(str(resource_path), str(resource_file_target_dir_path))
                else:
                    print(f"   WARNING: the file name of the resource '{resource_path.relative_to(self.allDslRootDirPath)}' is already existing in the target folder !")

    @staticmethod
    def _get_dict_from_json_file(json_file_path: Path) -> Optional[dict]:
        try:
            with json_file_path.open("r") as json_file:
                file_content_as_dict = json.load(json_file)
        except (OSError, json.JSONDecodeError) as e:
            print(f"        - Load json from file '{json_file_path}' failed: ", e)
            return None

        if not isinstance(file_content_as_dict, dict):
            print(f"        - Load json from file '{json_file_path}' failed: the read json is not a dict ({file_content_as_dict})")
            return None

        return file_content_as_dict

    @staticmethod
    def _write_dict_to_json_file(input_dict: dict, output_json_file_path: Path) -> bool:
        try:
            with output_json_file_path.open("w", newline="\n") as json_file:
                json.dump(input_dict, json_file, indent=4)
        except (OSError, TypeError, ValueError, OverflowError) as e:
            print(f"        - Write json to file '{output_json_file_path}' failed: ", e)
            return False
        return True

    def _merge_the_dsl_json_file_from_dsl_folders_into_one_file(self, dsl_json_file_name: str,
                                                                dsl_definition_files_folder_name: str,
                                                                dsl_dir_paths: List[Path],
                                                                dsl_host="127.169.0.0", dsl_port=40000) -> Optional[Tuple[Optional[Path], Optional[List[Path]]]]:
        # Create the target folder and the single DSL json file path
        dsl_folder_target_path = self.singleDslTargetDirPath / "main-dsl-folder"
        dsl_json_file_target_dir_path = dsl_folder_target_path / dsl_definition_files_folder_name
        print(f"- Create the single DSL json file target folder '{dsl_json_file_target_dir_path}'")
        dsl_json_file_target_dir_path.mkdir(parents=True, exist_ok=True)
        dsl_json_file_target_path = dsl_json_file_target_dir_path / dsl_json_file_name

        special_dsl_json_file_target_path_list = []

        # Merge dsl json files
        print(f"- Merge the {dsl_json_file_name} files from each 'DSL/{dsl_definition_files_folder_name}' into a single"
              f" {dsl_json_file_name} file in target '{dsl_definition_files_folder_name}'")
        single_dsl_json_dict = {
            "dsl.host": dsl_host,
            "dsl.port": dsl_port,
            "components": [],
        }
        for dsl_dir_path_index, dsl_dir_path in enumerate(dsl_dir_paths):
            dsl_json_file_path = dsl_dir_path / dsl_definition_files_folder_name / dsl_json_file_name
            dsl_json_dict = self._get_dict_from_json_file(dsl_json_file_path)
            if dsl_json_dict is None:
                print(f"   ERROR: impossible to get the json content of the dsl json file '{dsl_json_file_path.relative_to(self.allDslRootDirPath)}'"
                      f" ! So continue with others {dsl_json_file_name} files...")
                continue

            special_single_dsl_json_dict = {
                "dsl.host": dsl_host,
                "dsl.port": dsl_port + dsl_dir_path_index + 1,
                "components": [],
            }

            # Merge component in the single dsl json file
            dsl_json_components = dsl_json_dict.get("components", None)
            if not isinstance(dsl_json_components, list):
                print(f"   ERROR: impossible to get the components list from the dsl json file '{dsl_json_file_path.relative_to(self.allDslRootDirPath)}'"
                      f" ! So continue with others components in {dsl_json_file_name} file...")
                continue
            # noinspection GrazieInspection
            for dsl_json_component_index, dsl_json_component in enumerate(dsl_json_components):
                dsl_json_component_jar = dsl_json_component.get("jar", None)
                if dsl_json_component_jar is None:
                    print(f"   ERROR: impossible to get the 'jar' field of the component #{dsl_json_component_index} from the dsl json file"
                          f" '{dsl_json_file_path.relative_to(self.allDslRootDirPath)}' ! So continue with others components in {dsl_json_file_name} file...")
                    continue

                dsl_json_component_name = dsl_json_component.get("_name", None)
                if dsl_json_component_name is None:
                    print(f"   ERROR: impossible to get the '_name' field of the component #{dsl_json_component_index} from the dsl json file"
                          f" '{dsl_json_file_path.relative_to(self.allDslRootDirPath)}' ! So continue with others components in {dsl_json_file_name} file...")
                    continue
                dsl_json_component_configuration_srv_instance = dsl_json_component.get("configuration", {}).get("srv.instance", None)
                if dsl_json_component_configuration_srv_instance is None:
                    print(f"   ERROR: impossible to get the 'configuration/srv.instance' field of the component '{dsl_json_component_name}'"
                          f" (#{dsl_json_component_name}) from the dsl json file '{dsl_json_file_path.relative_to(self.allDslRootDirPath)}'"
                          f" ! So continue with others components in {dsl_json_file_name} file...")
                    continue

                # Build the DSL topology string
                dsl_topology_str = "..".join(dsl_dir_path.relative_to(self.allDslRootDirPath).parts)

                # Check if the "_name" and "srv.instance" are equal
                if dsl_json_component_name != dsl_json_component_configuration_srv_instance:
                    print(f"   WARNING: The component #{dsl_json_component_index} at '{dsl_topology_str}' node has a '_name' field value"
                          f" ('{dsl_json_component_name}') is different than 'srv.instance' value ('{dsl_json_component_configuration_srv_instance}')")

                # Update the DSL component name
                updated_name = f"{dsl_topology_str}..{dsl_json_component_name}"
                # print(f"    - Update the component name from '{dsl_json_component_name}' to '{updated_name}'")
                dsl_json_component["_name"] = updated_name

                # Update the DSL component configuration srv.instance
                updated_name = f"{dsl_topology_str}.{dsl_json_component_configuration_srv_instance}"
                # print(f"    - Update the component configuration 'srv.instance' from '{dsl_json_component_configuration_srv_instance}' to '{updated_name}'")
                dsl_json_component["configuration"]["srv.instance"] = updated_name

                # Add the component to the single DSL json file
                if dsl_json_component_jar.startswith("bin/generic-snmp") or dsl_json_component_jar.startswith("bin/dio-snmp-mock"):
                    special_single_dsl_json_dict["components"].append(dsl_json_component)
                else:
                    single_dsl_json_dict["components"].append(dsl_json_component)

            if len(special_single_dsl_json_dict["components"]) > 0:
                # Create the special target folder and the single DSL json file path
                special_dsl_folder_target_path = self.singleDslTargetDirPath / f"dsl-folder-{special_single_dsl_json_dict['dsl.port']}"
                special_dsl_json_file_target_dir_path = special_dsl_folder_target_path / dsl_definition_files_folder_name
                print(f"- Create the special single DSL json file target folder '{special_dsl_json_file_target_dir_path}'")
                special_dsl_json_file_target_dir_path.mkdir(parents=True, exist_ok=True)
                special_dsl_json_file_target_path = special_dsl_json_file_target_dir_path / dsl_json_file_name

                if not self._write_dict_to_json_file(special_single_dsl_json_dict, special_dsl_json_file_target_path):
                    print(f"   ERROR: impossible to write the single dsl json file '{special_dsl_json_file_target_path}' !")
                    return None

                special_dsl_json_file_target_path_list.append(special_dsl_json_file_target_path)

        # Write the single DSL json file to the target folder
        if not self._write_dict_to_json_file(single_dsl_json_dict, dsl_json_file_target_path):
            print(f"   ERROR: impossible to write the single dsl json file '{dsl_json_file_target_path}' !")
            return None

        return dsl_json_file_target_path, special_dsl_json_file_target_path_list

    @staticmethod
    def _initialise_log_xml_lines() -> List[str]:
        return [
            r"""<?xml version="1.0" encoding="UTF-8"?>""",
            r"""<Configuration>""",
        ]

    @staticmethod
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
    def _append_logger_to_log_xml_lines(dsl_log_xml_lines: list, service_name: str, namespace: str, trace_level: str) -> NoReturn:
        dsl_log_xml_lines.append(f"""        <Logger name="{namespace}" level="{trace_level}" additivity="false">""")
        dsl_log_xml_lines.append(f"""            <AppenderRef ref="{service_name}"/>""")
        dsl_log_xml_lines.append(r"""        </Logger>""")

    @staticmethod
    def _write_log_xml_lines(dsl_log_xml_lines: list, dsl_log_xml_path: Path) -> bool:
        dsl_log_xml_lines.append(r"""        <Root level="WARN">""")
        dsl_log_xml_lines.append(r"""            <AppenderRef ref="dsl" />""")
        dsl_log_xml_lines.append(r"""        </Root>""")
        dsl_log_xml_lines.append(r"""    </Loggers>""")
        dsl_log_xml_lines.append(r"""</Configuration>""")

        try:
            with dsl_log_xml_path.open("w", newline="\n") as target:
                target.writelines([f"{line}\n" for line in dsl_log_xml_lines])
        except (OSError, TypeError, ValueError) as e:
            print(f"        - Write '{dsl_log_xml_path}' file failed: ", e)
            return False

        return True

    def _build_the_single_dsl_log_xml_file_from_the_single_dsl_json_file(self, dsl_log_xml_file_name: str,
                                                                         dsl_json_file_path: Path,
                                                                         trace_level: str = "DEBUG",
                                                                         max_log_file_size: int = 10240000) -> bool:
        # Create the single DSL log4j.xml file path
        dsl_log_xml_file_path = dsl_json_file_path.parent / dsl_log_xml_file_name

        # Build the DSL log4j file
        print(f"- Build the single DSL {dsl_log_xml_file_name} file from the single DSL '{dsl_json_file_path}' file")
        print(f"    - Initialise the single DLS {dsl_log_xml_file_name} file lines")
        dsl_log_xml_lines = self._initialise_log_xml_lines()
        dsl_json_dict = self._get_dict_from_json_file(dsl_json_file_path)
        dsl_namespaces_by_service_name = {"dsl": ["dsl"]}
        if dsl_json_dict is None:
            print(f"   ERROR: impossible to get the json content of the dsl json file '{dsl_json_file_path}' !")
            return False
        for dsl_json_component_index, dsl_json_component in enumerate(dsl_json_dict.get("components", [])):
            dsl_json_component_enable_status = dsl_json_component.get("enable", True)
            if not dsl_json_component_enable_status:
                continue

            dsl_json_component_jar = dsl_json_component.get("jar", None)
            if dsl_json_component_jar is None:
                print(f"   ERROR: impossible to get the 'jar' field of the component #{dsl_json_component_index} from the dsl json file '{dsl_json_file_path}' !")
                return False

            dsl_json_component_name = dsl_json_component.get("_name", None)
            if dsl_json_component_name is None:
                print(f"   ERROR: impossible to get the '_name' field of the component #{dsl_json_component_index} from the dsl json file '{dsl_json_file_path}' !")
                return False

            dsl_json_component_configuration_srv_instance = dsl_json_component.get("configuration", {}).get("srv.instance", None)
            if dsl_json_component_configuration_srv_instance is None:
                print(f"   ERROR: impossible to get the 'configuration/srv.instance' field of the component"
                      f" '{dsl_json_component_name}' (#{dsl_json_component_name}) from the dsl json file '{dsl_json_file_path}' !")
                return False

            # Builds components list to generate loggers and appenders
            # Special management for RM-MOCK
            elif dsl_json_component_jar.startswith("bin/rm-mock-"):
                remote_identifier = dsl_json_component.get("configuration", {}).get("remote.identifier", None)
                if remote_identifier is not None:
                    dsl_namespaces_by_service_name[dsl_json_component_configuration_srv_instance] = [remote_identifier]
            # Normal case
            else:
                dsl_namespaces_by_service_name[dsl_json_component_configuration_srv_instance] = [dsl_json_component_configuration_srv_instance]

        # Appends appenders
        dsl_log_xml_lines.append(r"""    <Appenders>""")
        for service_name in dsl_namespaces_by_service_name.keys():
            # print(f"    - Append the '{dsl_json_component_name}' component configuration to the single DLS {dsl_log_xml_file_name} file lines")
            self._append_appender_to_log_xml_lines(dsl_log_xml_lines, "logs", service_name, max_log_file_size)
        dsl_log_xml_lines.append(r"""    </Appenders>""")

        # Appends loggers
        dsl_log_xml_lines.append(r"""    <Loggers>""")
        for service_name, namespaces in dsl_namespaces_by_service_name.items():
            for namespace in namespaces:
                # Creates loggers
                self._append_logger_to_log_xml_lines(dsl_log_xml_lines, service_name, namespace, trace_level)

        print(f"    - Write the the single DLS {dsl_log_xml_file_name} file '{dsl_log_xml_file_path}'")
        if not self._write_log_xml_lines(dsl_log_xml_lines, dsl_log_xml_file_path):
            return False
        return True


class PilDeploymentDescriptionParser(DeploymentDescriptionDeployer):
    pilFolderName = "pil-target"
    pilDockerFileFolderName = "dockerfiles"
    pilCommonNetworkName = "pil-common-network"
    runningDeploymentLogFolderName = "logs"
    listOfDockerImagesUsedKey = "listOfDockerImagesUsed"

    def __init__(self, deployment_folder_path: Path):
        self.pilDirPath = deployment_folder_path / self.pilFolderName

        DeploymentDescriptionDeployer.__init__(self, self.pilDirPath)

        self.dockerfilesDirPath = self.pilDirPath / self.pilDockerFileFolderName
        self.logDirPath = self.pilDirPath / self.runningDeploymentLogFolderName

        self._deployment_dict = None

    def _get_the_main_parent_component_group_dockercompose_file_path(self, dict_path: DictPath) -> Path:
        main_parent_component_group_dict_path = self._get_main_parent_component_group_dict_path(dict_path)
        main_parent_component_group_name = self._get_group_name_from_definition_key(main_parent_component_group_dict_path.get_the_last_step_of_the_path())
        main_parent_component_group_name_for_docker = main_parent_component_group_name.lower()
        main_parent_component_group_dockercompose_file_path = self.pilDirPath / f"{main_parent_component_group_name_for_docker}.dockercompose"
        return main_parent_component_group_dockercompose_file_path

    def _get_the_service_name_header(self, dict_path: DictPath) -> str:
        parents_component_groups_names = self._get_parents_component_groups_names(dict_path)
        parents_component_groups_names.reverse()
        service_name_header = "-".join(parents_component_groups_names)
        return service_name_header

    def _get_the_component_name_version_environments_variables_and_associated_service_and_container_name(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> Tuple[str, str, dict, str, str]:
        service_name_header = self._get_the_service_name_header(dict_path)

        component_name, components_version = self._get_the_component_name_and_version(dict_path, path_based_dict)
        gan_docker_images_version_prefix = self._deployment_dict.get(self.key_words["label_of_a_pil_section"], {}).get("dockerImagesInfo", {}).get("ganDockerImagesVersionPrefix", "")
        if components_version != "latest":
            components_version = gan_docker_images_version_prefix + components_version

        component_environment_variables_by_name = self._get_the_component_environments_variables(dict_path, path_based_dict)

        component_description_dict = path_based_dict.get_the_value_pointed_by_a_dict_path(dict_path)
        component_description_name = component_description_dict.get(self.key_words["label_of_the_component_description_name"], None)

        service_name = self._get_component_associated_service_name(service_name_header, component_name, component_description_name, component_environment_variables_by_name).lower()
        container_name = f"pil-{service_name}"

        return component_name, components_version, component_environment_variables_by_name, service_name, container_name

    @staticmethod
    def _get_component_associated_service_name(service_header_name: str, component_name: str, component_description_name: str = None,
                                               component_environments_variables: dict = None) -> str:
        service_name = f'{service_header_name}'
        if component_description_name is not None:
            service_name += f'-{component_description_name}'
        else:
            service_name += f'-{component_name}'
        return service_name


class PilDeployer(PilDeploymentDescriptionParser):
    def __init__(self, deployment_folder_path: Path):
        PilDeploymentDescriptionParser.__init__(self, deployment_folder_path)

        self.pilDatabaseComponentName = None
        self.jaegerComponentName = None
        self._first_dockercompose_file_path = None
        self._first_service_by_ip_address_on_all_dockercomposes = None
        self._main_component_group_dockercompose_final_lines = None

    def deploy_from_deployment_description_json_file(self, deployment_description_json_file_path: Path) -> NoReturn:
        if self.is_gan_components_running():
            raise UserWarning(f"A deployment is running on the folder '{self.pilDirPath}', stop it before any deployment")

        self._deployment_dict = self._get_dict_from_json_file(deployment_description_json_file_path)

        self.pilDatabaseComponentName = self._deployment_dict.get(self.key_words["label_of_a_pil_section"], {}).get("dockerImagesInfo", {}).get("pilDatabaseComponentName", None)
        if self.pilDatabaseComponentName is None:
            raise UserWarning(f"The PIL database component name is not defined")

        self.jaegerComponentName = self._deployment_dict.get(self.key_words["label_of_a_jaeger_section"], {}).get("dockerImagesInfo", {}).get("jaegerComponentName", None)
        if self.jaegerComponentName is None:
            raise UserWarning("The jaeger component name is not defined")

        if self.pilDirPath.exists():
            print(f"     - Delete '{self.pilDirPath}'")
            shutil.rmtree(self.pilDirPath, ignore_errors=True)
        self.pilDirPath.mkdir(parents=True, exist_ok=True)
        self.dockerfilesDirPath.mkdir(parents=True, exist_ok=True)

        self._first_dockercompose_file_path = None
        self._first_service_by_ip_address_on_all_dockercomposes = {}
        self._parse_the_deployment_description_json_file(deployment_description_json_file_path)

        self._append_pil_network_definition_to_the_first_dockercompose_file()
        self._set_deployed_status(True)

    def _append_pil_network_definition_to_the_first_dockercompose_file(self) -> NoReturn:
        if self._first_dockercompose_file_path is None:
            raise UserWarning(f"No dockercompose build !")

        pil_network_dict = self._deployment_dict.get(self.key_words["label_of_a_pil_section"], {}).get("pilNetwork", {})
        pil_subnet = pil_network_dict.get("subnet", None)
        if pil_subnet is None:
            raise UserWarning(f"The PIL network parameter 'subnet' is not defined")
        pil_gateway = pil_network_dict.get("gateway", None)
        if pil_gateway is None:
            raise UserWarning(f"The PIL network parameter 'gateway' is not defined")

        dockercompose_lines = [
            f'',
            f'networks:',
            f'    {self.pilCommonNetworkName}:',
            f'        driver: bridge',
            f'        ipam:',
            f'            driver: default',
            f'            config:',
            f'                - subnet: {pil_subnet}',
            f'                  gateway: {pil_gateway}',
            f'',
        ]

        self._append_file_content(self._first_dockercompose_file_path, dockercompose_lines)

    def _component_group_deployment_starting(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        if not self._is_parent_group_is_the_main_parent_group(dict_path):
            return

        main_parent_component_group_dockercompose_file_path = self._get_the_main_parent_component_group_dockercompose_file_path(dict_path)

        self._main_component_group_dockercompose_final_lines = []

        if self._first_dockercompose_file_path is None:
            self._first_dockercompose_file_path = main_parent_component_group_dockercompose_file_path

        print(f"         - Make a PIL deployment of the '{main_parent_component_group_dockercompose_file_path.stem}' component group"
              f" and build the '{main_parent_component_group_dockercompose_file_path.relative_to(self.deploymentDirPath)}' file")

        dockercompose_lines = [
            f'# docker-compose -p pil-{main_parent_component_group_dockercompose_file_path.stem}-compose -f "{main_parent_component_group_dockercompose_file_path.name}" up --build -d',
            f'# docker-compose -p pil-{main_parent_component_group_dockercompose_file_path.stem}-compose -f "{main_parent_component_group_dockercompose_file_path.name}" down --rmi all  --remove-orphans',
            f'# docker exec -it pil-{main_parent_component_group_dockercompose_file_path.stem}-[container_type] bash',
            f'',
            f'version: "2.1"',
            f'services:',
            f'',
        ]

        self._initialize_file_content(main_parent_component_group_dockercompose_file_path, dockercompose_lines)

    def _component_group_deployment_ending(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        if not self._is_parent_group_is_the_main_parent_group(dict_path):
            return

        main_parent_component_group_dockercompose_file_path = self._get_the_main_parent_component_group_dockercompose_file_path(dict_path)

        if len(self._main_component_group_dockercompose_final_lines) > 0:
            print(f"         - Finalize the PIL deployment of the '{main_parent_component_group_dockercompose_file_path.stem}' component group")
            self._append_file_content(main_parent_component_group_dockercompose_file_path, [''] + self._main_component_group_dockercompose_final_lines)

    def _component_group_database_deployment(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        service_name_header = self._get_the_service_name_header(dict_path)

        main_parent_component_group_dockercompose_file_path = self._get_the_main_parent_component_group_dockercompose_file_path(dict_path)

        database_host, database_port = self._get_database_host_and_port_from_description_dict_path(dict_path, path_based_dict)

        component_name = self.pilDatabaseComponentName
        service_name = self._get_component_associated_service_name(service_name_header, component_name).lower()



        gan_context_images_repository_path = self._deployment_dict.get(self.key_words["label_of_a_pil_section"], {}).get("dockerImagesInfo", {}).get("ganContextImagesRepositoryPath", None)
        if gan_context_images_repository_path is None:
            raise UserWarning(f"The PIL gan context images repository path is not defined")

        pil_database_component_image_version = self._deployment_dict.get(self.key_words["label_of_a_pil_section"], {}).get("dockerImagesInfo", {}).get("pilDatabaseComponentImageVersion", None)
        if pil_database_component_image_version is None:
            raise UserWarning(f"The PIL database component version is not defined")

        print(f"             - Create the '{component_name}' associated PIL docker file in '{self.dockerfilesDirPath.relative_to(self.deploymentDirPath)}' folder")
        self._create_the_associated_component_pil_dockerfile(component_name, pil_database_component_image_version, gan_context_images_repository_path)

        print(f"             - Create the '{service_name}' service in the dockercompose file '{main_parent_component_group_dockercompose_file_path.relative_to(self.deploymentDirPath)}'")

        syslog_is_enabled, _, _, _ = self._get_syslog_information(path_based_dict)

        dockercompose_lines = [
            f'    {service_name}:',
            f'        image: pil-{service_name}:{pil_database_component_image_version}',
            f'        container_name: pil-{service_name}',
            f'        build:',
            f'            context: ./{self.pilDockerFileFolderName}',
            f'            dockerfile: pil-{component_name}.dockerfile',
            f'        environment:',
            f'            POSTGRES_PASSWORD: "postgres"',
            f'            # Bug with the use of this parameter: POSTGRES_LOG_DEST: "[[ {str(syslog_is_enabled).lower()} ]] && \\"syslog\\" || \\"csvlog\\""',
            f'            POSTGRES_AUTH_USERS: "postgres,atmosphere"',
            f'            POSTGRES_LISTENING_PORT: "{database_port}"',
        ]

        dockercompose_lines += self._get_component_network_mode_dockercompose_lines(service_name, database_host)

        dockercompose_lines += [
            f'        healthcheck:',
            f'            test: [ "CMD-SHELL", "pg_isready", "-q", "-h", "{database_host}", "-p", "{database_port}", "||", "exit", "1"]',
            f'            timeout: 30s',
            f'            interval: 10s',
            f'            retries: 3',
            f'        volumes:',
            f'            - {service_name}:/var/lib/postgresql/data',
            f'',
        ]

        self._append_file_content(main_parent_component_group_dockercompose_file_path, dockercompose_lines)

        self._main_component_group_dockercompose_final_lines += [
            f'volumes:',
            f'    {service_name}:',
            f'',
        ]

    def _component_deployment_starting(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        main_parent_component_group_dockercompose_file_path = self._get_the_main_parent_component_group_dockercompose_file_path(dict_path)
        component_name, components_version, component_environment_variables_by_name, service_name, container_name = self._get_the_component_name_version_environments_variables_and_associated_service_and_container_name(dict_path, path_based_dict)

        jaeger_component_name = self.jaegerComponentName
        jaeger_component_images_repository_path = self._deployment_dict.get(self.key_words["label_of_a_jaeger_section"],{}).get("dockerImagesInfo", {}).get("ganContextImagesRepositoryPath", None)

        if jaeger_component_images_repository_path is None:
            raise UserWarning(f"The Jaeger context images repository path is not defined")

        jaeger_component_image_version = self._deployment_dict.get(self.key_words["label_of_a_jaeger_section"], {}).get("dockerImagesInfo", {}).get("jaegerComponentImageVersion", None)

        if jaeger_component_image_version is None:
            raise UserWarning(f"The Jaeger component version is not defined")

        self._create_the_associated_component_pil_dockerfile(jaeger_component_name, jaeger_component_image_version,jaeger_component_images_repository_path)

        print(f"- Create the '{service_name}' service in the dockercompose file '{main_parent_component_group_dockercompose_file_path.relative_to(self.deploymentDirPath)}'")

        syslog_is_enabled, syslog_host, syslog_port, syslog_app_name_prefix = self._get_syslog_information(path_based_dict)

        gan_component_images_repository_path = self._deployment_dict.get(self.key_words["label_of_a_pil_section"], {}).get("dockerImagesInfo", {}).get("ganComponentImagesRepositoryPath", None)
        if gan_component_images_repository_path is None:
            raise UserWarning(f"The PIL gan component images repository path is not defined")

        self._create_the_associated_component_pil_dockerfile(component_name, components_version, gan_component_images_repository_path)

        print(f"             - Create the '{service_name}' service in the dockercompose file '{main_parent_component_group_dockercompose_file_path.relative_to(self.deploymentDirPath)}'")

        syslog_is_enabled, syslog_host, syslog_port, syslog_app_name_prefix = self._get_syslog_information(path_based_dict)

        dockercompose_lines = [
            f'    {service_name}:',
            f'        image: pil-{service_name}:{components_version}',
            f'        container_name: {container_name}',
            f'        build:',
            f'            context: ./{self.pilDockerFileFolderName}',
            f'            dockerfile: pil-{component_name}.dockerfile',
            f'        environment:',
        ]

        for environment_name, environment_value in component_environment_variables_by_name.items():
            environment_value_to_use = json.dumps(environment_value)
            dockercompose_lines.append(f'            {environment_name}: {environment_value_to_use}')

        pil_postgres_password = self._deployment_dict.get(self.key_words["label_of_a_pil_section"], {}).get("dockerImagesInfo", {}).get("pilPostgresPassword", None)
        if pil_postgres_password is None:
            raise UserWarning(f"The PIL postgres user password is not defined")

        pil_atmosphere_password = self._deployment_dict.get(self.key_words["label_of_a_pil_section"], {}).get("dockerImagesInfo", {}).get("pilAtmospherePassword", None)
        if pil_atmosphere_password is None:
            raise UserWarning(f"The PIL atmosphere user password is not defined")

        if "sqlHost" in component_environment_variables_by_name:
            dockercompose_lines += [
                f'            POSTGRES_PASSWORD: "{pil_postgres_password}"',
                f'            PGPASSWORD: "{pil_postgres_password}"',
                f'            ATMOSPHERE_PASSWORD: "{pil_atmosphere_password}"',
            ]

        dockercompose_lines += [f'            SYSLOG_ENABLED: "{str(syslog_is_enabled).lower()}"']
        if syslog_is_enabled:
            dockercompose_lines += [
                f'            SYSLOG_HOST: "{syslog_host}"',
                f'            SYSLOG_PORT: "{syslog_port}"',
                f'            SYSLOG_APP_NAME_PREFIX: "{syslog_app_name_prefix}"',
            ]
        else:
            dockercompose_lines += [
                f'            SYSLOG_HOST: "NOT_USED"',
                f'            SYSLOG_PORT: "NOT_USED"',
                f'            SYSLOG_APP_NAME_PREFIX: "NOT_USED"',
            ]

        component_host = component_environment_variables_by_name.get("host", None)
        if component_host is None:
            raise UserWarning(f"The '{dict_path}' component parameter 'host' is not defined")
        dockercompose_lines += self._get_component_network_mode_dockercompose_lines(service_name, component_host)

        self._append_file_content(main_parent_component_group_dockercompose_file_path, dockercompose_lines)
        # Add a dependency on the database to start the backend after the database
        # (except for workstation which has no dependency on the database)
        if self._get_container_group(container_name) != "workstation":
            database_dict_path = self._get_from_here_to_the_top_of_the_dict_path_to_the_database_to_use(dict_path, path_based_dict)
            database_parents_component_groups_names = self._get_parents_component_groups_names(database_dict_path)
            database_parents_component_groups_names.reverse()
            database_service_name_header = "-".join(database_parents_component_groups_names)

            dockercompose_lines += [
                f'        privileged: true',
                f'        depends_on:',
                f'            {self._get_component_associated_service_name(database_service_name_header, self.pilDatabaseComponentName)}:',
                f'                condition: service_healthy',
                f'',
            ]

            dockercompose_lines += [f'']
            self._append_file_content(main_parent_component_group_dockercompose_file_path, dockercompose_lines)




    def _create_the_associated_component_pil_dockerfile(self, component_name: str, components_version: str, image_repository: str):
        dockerfile_path = self.dockerfilesDirPath / f"pil-{component_name}.dockerfile"

        if dockerfile_path.exists():
            print(f"             - The '{component_name}' associated PIL docker file '{dockerfile_path.relative_to(self.deploymentDirPath)}' is already existing")
            return

        print(f"             - Create the '{component_name}' associated PIL docker file '{dockerfile_path.relative_to(self.deploymentDirPath)}'")

        component_associated_image_name = self._get_component_associated_image_name(component_name, components_version, image_repository)

        self._deployment_dict.setdefault(self.runningDeploymentStatusKey, {}).setdefault(self.listOfDockerImagesUsedKey, []).append(component_associated_image_name)

        dockerfile_lines = [
            f'# docker image ls',
            f'# docker build -f ./{self.pilDockerFileFolderName}/pil-{component_name}.dockerfile -t pil-{component_name}:TEST ./dockerfiles/',
            f'# docker image rm pil-{component_name}:TEST',
            f'# docker run -it --name pil-{component_name}-container --rm pil-{component_name}:TEST bash',
            f'# docker cp pil-{component_name}-container:/usr/gan-ms/{component_name}/equinox.sh ~/[destination folder]/',
            f'# docker ps [-a]',
            f'',
            f'FROM {component_associated_image_name}',
            f'',
        ]

        env_java_tool_options = []
        gan_docker_containers_java_options_xms = self._deployment_dict.get(self.key_words["label_of_a_pil_section"],{}).get("dockerContainersInfo", {}).get("javaOptionXms", {})
        jaeger_docker_containers_java_options_xms = self._deployment_dict.get(self.key_words["label_of_a_jaeger_section"],{}).get("dockerContainersInfo", {}).get("javaOptionXms", {})

        if component_name in gan_docker_containers_java_options_xms:
            component_xms_value : Any = gan_docker_containers_java_options_xms[component_name]
        elif component_name in jaeger_docker_containers_java_options_xms:
            component_xms_value : Any = jaeger_docker_containers_java_options_xms[component_name]
        else:
            component_xms_value = None

        if component_xms_value is not None:
            env_java_tool_options.append("-Xms" + component_xms_value)
        else:
            if "--default--" in gan_docker_containers_java_options_xms:
                default_xms_value : Any = gan_docker_containers_java_options_xms["--default--"]
            elif "--default--" in jaeger_docker_containers_java_options_xms:
                default_xms_value : Any = jaeger_docker_containers_java_options_xms["--default--"]
            else:
                default_xms_value = None

            if default_xms_value is not None:
                env_java_tool_options.append("-Xms" + default_xms_value)

        gan_docker_containers_java_options_xmx = self._deployment_dict.get(self.key_words["label_of_a_pil_section"], {}).get("dockerContainersInfo", {}).get("javaOptionXmx", {})
        jaeger_docker_containers_java_options_xmx = self._deployment_dict.get(self.key_words["label_of_a_jaeger_section"],{}).get("dockerContainersInfo", {}).get("javaOptionXmx", {})

        if component_name in gan_docker_containers_java_options_xmx:
            component_xmx_value = gan_docker_containers_java_options_xmx[component_name]
        elif component_name in jaeger_docker_containers_java_options_xmx:
            component_xmx_value = jaeger_docker_containers_java_options_xmx[component_name]
        else:
            component_xmx_value = None

        if component_xmx_value is not None:
            env_java_tool_options.append("-Xmx" + component_xmx_value)
        else:
            if "--default--" in gan_docker_containers_java_options_xmx:
                default_xmx_value = gan_docker_containers_java_options_xmx["--default--"]
            elif "--default--" in jaeger_docker_containers_java_options_xmx:
                default_xmx_value = jaeger_docker_containers_java_options_xmx["--default--"]
            else:
                default_xmx_value = None

            if default_xmx_value is not None:
                env_java_tool_options.append("-Xmx" + default_xmx_value)

        if len(env_java_tool_options) > 0:
            dockerfile_lines += [
                f'ENV JAVA_TOOL_OPTIONS "' + ' '.join(env_java_tool_options) + '"',
                f'',
            ]

        self._initialize_file_content(dockerfile_path, dockerfile_lines)

    def _initialize_file_content(self, file_path: Path, content_lines: List[str]) -> NoReturn:
        try:
            with file_path.open("w", newline="\n") as target:
                target.writelines("\n".join(content_lines))
        except (OSError, TypeError, ValueError) as e:
            print(f"             - Write '{file_path.relative_to(self.deploymentDirPath)}' file failed: ", e)
            raise UserWarning(f"Write '{file_path.relative_to(self.deploymentDirPath)}' file failed: {e}")

    def _append_file_content(self, file_path: Path, content_lines: List[str]) -> NoReturn:
        try:
            with file_path.open("a", newline="\n") as target:
                target.writelines("\n".join(content_lines))
        except (OSError, TypeError, ValueError) as e:
            print(f"             - Append '{file_path.relative_to(self.deploymentDirPath)}' file failed: ", e)
            raise UserWarning(f"Append '{file_path.relative_to(self.deploymentDirPath)}' file failed: {e}")

    def _get_syslog_information(self, path_based_dict: PathBasedDictionary) -> tuple:
        pil_section_dict = path_based_dict.get_the_value_pointed_by_a_dict_path(
            DictPath(from_dict_path_as_list=[self.key_words["label_of_a_pil_section"]]))
        jaeger_section_dict=path_based_dict.get_the_value_pointed_by_a_dict_path(
            DictPath(from_dict_path_as_list=[self.key_words["label_of_a_jaeger_section"]]))
        syslog_dict = pil_section_dict.get("syslog", None)
        syslog_dict_jaeger = jaeger_section_dict.get("syslog", None)
        if syslog_dict is None and syslog_dict_jaeger is None:
            raise UserWarning(f"The PIL syslog information are not present")

        is_enabled = syslog_dict.get("isEnabled", None)
        is_enabled_jaeger=syslog_dict_jaeger.get("isEnabled", None)
        if is_enabled is None and is_enabled_jaeger is None:
            raise UserWarning(f"The PIL syslog information 'is_enabled' is not defined")

        if is_enabled is not True and is_enabled_jaeger is not True:
            #return is_enabled, None, None, None, is_enabled_jaeger
            return is_enabled, None, None, None
        host = syslog_dict.get("host", None)
        host_jaeger=syslog_dict_jaeger.get("host", None)
        if host is None and host_jaeger is None:
            raise UserWarning(f"The PIL syslog information 'host' is not defined")

        port = syslog_dict.get("port", None)
        port_jaeger=syslog_dict_jaeger.get("port", None)
        if port is None and port_jaeger is None:
            raise UserWarning(f"The PIL syslog information 'port' is not defined")

        app_name_prefix = syslog_dict.get("appNamePrefix", None)
        app_name_prefix_jaeger=syslog_dict_jaeger.get("appNamePrefix", None)
        if app_name_prefix is None and app_name_prefix_jaeger is None:
            raise UserWarning(f"The PIL syslog information 'appNamePrefix' is not defined")

       # return is_enabled, host, port, app_name_prefix, is_enabled_jaeger,host_jaeger,port_jaeger,app_name_prefix_jaeger
        return is_enabled, host, port, app_name_prefix

    @staticmethod
    def _get_component_associated_image_name(component_name: str, components_version: str, image_repository: str) -> str:
        if "gan-docker" in image_repository:
            component_associated_image_name = f"{image_repository}/{component_name}:{components_version}"
        else:
            component_associated_image_name = f"{image_repository}-{component_name}:{components_version}"
        return component_associated_image_name

    def _get_component_network_mode_dockercompose_lines(self, component_service_name: str, component_ip_address: str) -> List[str]:
        if component_ip_address in self._first_service_by_ip_address_on_all_dockercomposes:
            service_name = self._first_service_by_ip_address_on_all_dockercomposes[component_ip_address]
            return self._get_component_network_mode_dockercompose_lines_with_service_format(service_name)
        else:
            self._first_service_by_ip_address_on_all_dockercomposes[component_ip_address] = component_service_name
            return self._get_component_network_mode_dockercompose_lines_with_network_format(self.pilCommonNetworkName, component_ip_address)

    @staticmethod
    def _get_component_network_mode_dockercompose_lines_with_network_format(network_name: str, ipv4_address: str) -> List[str]:
        dockercompose_lines = [
            f'        networks:',
            f'            {network_name}:',
            f'                ipv4_address: "{ipv4_address}"',
        ]
        return dockercompose_lines

    @staticmethod
    def _get_component_network_mode_dockercompose_lines_with_service_format(service_name: str) -> List[str]:
        dockercompose_lines = [f'        network_mode: "service:{service_name}"']
        return dockercompose_lines


class PilRunning(PilDeploymentDescriptionParser):
    def __init__(self, deployment_folder_path: Path):
        PilDeploymentDescriptionParser.__init__(self, deployment_folder_path)
        self._actionToBePerformed = None

    def save_the_basic_docker_images_used(self) -> NoReturn:
        if platform.system() == "Windows":
            print(" - Not allowed on Windows")
            return

        if not self.is_gan_components_deployed():
            print(" - The gan components dockercompose files are not created")
            return

        used_docker_images, used_docker_images_hash = self._get_the_used_docker_images_list_and_hash()

        file_path = self.pilDirPath / f"pil-docker-images-{used_docker_images_hash}.tar.gz"

        print(f" - Pull the docker images")
        for used_docker_image in used_docker_images:
            print(f"      - Pull {used_docker_image}")
            command_text = "docker pull " + used_docker_image
            log_file_path = self.pilDirPath / "pull-docker-images.log"
            log_file_path.parent.mkdir(parents=True, exist_ok=True)
            complete_process = run_subprocess(log_file_path, command_text, current_working_directory=self.pilDirPath, shell=True)
            if complete_process.returncode != 0:
                print(f"        ! Pull docker image {used_docker_image} failed")
                return

        print(f" - Save the docker images")
        command_text = "docker save " + " ".join(used_docker_images) + f' | gzip > "{file_path}"'
        log_file_path = self.pilDirPath / "save-docker-images.log"
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        complete_process = run_subprocess(log_file_path, command_text, current_working_directory=self.pilDirPath, shell=True)
        if complete_process.returncode != 0:
            print(f"        ! Save docker images failed")

    def load_the_basic_docker_images_to_used(self, file_to_load: Path, do_not_check_the_used_components_hash: bool = False) -> NoReturn:
        if platform.system() == "Windows":
            print(" - Not allowed on Windows")
            return

        if not self.is_gan_components_deployed():
            print(" - The gan components dockercompose files are not created")
            return

        if not file_to_load.is_file():
            print(" - The given path doesn't exist or it isn't a file path")
            return

        _, used_docker_images_hash = self._get_the_used_docker_images_list_and_hash()

        if not do_not_check_the_used_components_hash and used_docker_images_hash not in file_to_load.name:
            print(" ! The gan components dockercompose files have not the expected hash")
            return

        print(f" - Load the docker images from '{file_to_load}'")
        command_text = f'docker load -i "{file_to_load}"'
        log_file_path = self.pilDirPath / "load-docker-images.log"
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        complete_process = run_subprocess(log_file_path, command_text, current_working_directory=file_to_load.parent, shell=True)
        if complete_process.returncode != 0:
            print(f"        ! Load docker images failed")

    def remove_the_basic_docker_images_used(self) -> NoReturn:
        if platform.system() == "Windows":
            print(" - Not allowed on Windows")
            return

        if not self.is_gan_components_deployed():
            print(" - The gan components dockercompose files are not created")
            return

        if self.is_gan_components_running():
            print(" - The gan components containers are running")
            return

        used_docker_images, used_docker_images_hash = self._get_the_used_docker_images_list_and_hash()

        print(f" - Remove the docker images")
        for used_docker_image in used_docker_images:
            print(f"      - Remove {used_docker_image}")
            command_text = "docker rmi " + used_docker_image
            log_file_path = self.pilDirPath / "remove-docker-images.log"
            log_file_path.parent.mkdir(parents=True, exist_ok=True)
            complete_process = run_subprocess(log_file_path, command_text, current_working_directory=self.pilDirPath, shell=True)
            if complete_process.returncode != 0:
                print(f"        ! Remove docker image {used_docker_image} failed")

    def _get_the_used_docker_images_list_and_hash(self):
        used_docker_images = self._get_running_status_from_running_deployment_dict(self.listOfDockerImagesUsedKey, default_value=[])
        hash_builder = hashlib.sha256()
        for used_docker_image in used_docker_images:
            hash_builder.update(used_docker_image.encode())
        return used_docker_images, hash_builder.hexdigest()

    def start(self, keep_the_intermediate_images=False) -> NoReturn:
        if platform.system() == "Windows":
            print(" - Not allowed on Windows")
            return

        if not self.is_gan_components_deployed():
            print(" - The gan components dockercompose files are not created")
            return

        if self.is_gan_components_running():
            print(" - Gan components containers are already running")
            return

        dockercompose_path_results: List[Path] = list(self.pilDirPath.glob(f"./*.dockercompose"))

        print(f" - Start PIL")
        command_arguments = ["docker-compose", "-p", "pil-session"]

        for dockercompose_path in dockercompose_path_results:
            command_arguments += ["-f", dockercompose_path.name]

        command_arguments += ["up", "-d"]

        if not keep_the_intermediate_images:
            command_arguments += ["--build", "--force-recreate"]

        log_file_path = self.pilDirPath / "pil-session.log"
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        complete_process = run_subprocess(log_file_path, command_arguments, current_working_directory=self.pilDirPath)
        if complete_process.returncode != 0:
            print(f"        ! Start PIL dockercomposes failed")

        self._read_the_running_deployment_dict()
        self._set_gan_components_running_status(True)

    def logs(self) -> NoReturn:
        if platform.system() == "Windows":
            print(" - Not allowed on Windows")
            return

        if not self.is_gan_components_running():
            print(" - No gan components containers are running")
            return

        if self.logDirPath.exists():
            shutil.rmtree(self.logDirPath, ignore_errors=True)
        self.logDirPath.mkdir(parents=True, exist_ok=True)

        print(f" - Get the containers logs")
        self._get_container_log()

    def stop(self, keep_the_intermediate_images: bool = False, do_not_get_logs: bool = False) -> NoReturn:
        if platform.system() == "Windows":
            print(" - Not allowed on Windows")
            return

        if not self.is_gan_components_running():
            print(" - No gan components containers to stop")
            return

        if not do_not_get_logs:
            self.logs()

        print(f" - Stop PIL")
        command_arguments = ["docker-compose", "-p", "pil-session"]

        dockercompose_path_results: List[Path] = list(self.pilDirPath.glob(f"./*.dockercompose"))
        for dockercompose_path in dockercompose_path_results:
            command_arguments += ["-f", dockercompose_path.name]

        command_arguments += ["down", "--remove-orphans"]

        if not keep_the_intermediate_images:
            command_arguments += ["--rmi", "all"]

        log_file_path = self.pilDirPath / "pil-session.log"
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        complete_process = run_subprocess(log_file_path, command_arguments, current_working_directory=self.pilDirPath)
        if complete_process.returncode != 0:
            print(f"        ! Stop PIL dockercomposes failed")

        self._read_the_running_deployment_dict()
        self._set_gan_components_running_status(False)

    def _get_container_log(self) -> NoReturn:
        self._perform_the_action("getContainerLog")

    def _perform_the_action(self, action: str) -> NoReturn:
        self._actionToBePerformed = action

        self._deployment_dict = self._get_dict_from_json_file(self.runningDeploymentDescriptionJsonFile)
        self.parse_deployment_description_dict(self._deployment_dict)

    def _component_deployment_starting(self, dict_path: DictPath, path_based_dict: PathBasedDictionary) -> NoReturn:
        if self._actionToBePerformed not in ("getContainerLog",):
            return

        _, _, _, service_name, container_name = self._get_the_component_name_version_environments_variables_and_associated_service_and_container_name(dict_path, path_based_dict)

        print(f"             - Get the '{container_name}' logs")

        print(f"                 - Get container docker log")
        container_docker_log_folder_path = self.logDirPath / f"{container_name}.docker.log"
        command_text = f'docker logs -t {container_name} > "{container_docker_log_folder_path}"'
        log_file_path = self.pilDirPath / "get-container-docker-logs.log"
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        complete_process = run_subprocess(log_file_path, command_text, current_working_directory=self.pilDirPath, shell=True)
        if complete_process.returncode != 0:
            print(f"        ! Get docker container log failed")

        print(f"                 - Make a copy of the logs inside the container")
        command_arguments = ["docker", "exec", container_name, "/bin/bash", "-c", "mkdir -p /tmp_logs; cp -r /usr/gan-ms/*/logs /tmp_logs"]

        log_file_path = self.pilDirPath / f"container-inside-logs-copy.log"
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        complete_process = run_subprocess(log_file_path, command_arguments, current_working_directory=self.pilDirPath)
        if complete_process.returncode != 0:
            print(f"             ! Make a inside copy of the '{container_name}' container logs failed")

        print(f"                 - Make a copy of the logs from the container")
        container_log_folder_path = self.logDirPath / container_name
        container_log_folder_path.parent.mkdir(parents=True, exist_ok=True)
        command_arguments = ["docker", "cp", f"{container_name}:/tmp_logs/logs", container_log_folder_path]

        log_file_path = self.pilDirPath / f"container-logs-copy.log"
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        complete_process = run_subprocess(log_file_path, command_arguments, current_working_directory=self.pilDirPath)
        if complete_process.returncode != 0:
            print(f"             ! Make a copy of the '{container_name}' container logs failed")

        print(f"                 - Delete the logs temporary folder inside the container")
        command_arguments = ["docker", "exec", container_name, "/bin/bash", "-c", "rm -R /tmp_logs"]

        log_file_path = self.pilDirPath / f"container-inside-logs-delete.log"
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        complete_process = run_subprocess(log_file_path, command_arguments, current_working_directory=self.pilDirPath)
        if complete_process.returncode != 0:
            print(f"             ! Delete the logs temporary folder inside the '{container_name}' container failed")


if __name__ == "__main__":

    # Get the script path
    parameters_dict = {}
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        print("The script is running in a PyInstaller bundle")
        this_script_dir_path = Path(sys.executable).parent.absolute()

        # Check the presence of a parameters json file
        parameters_json_path = Path(__file__).resolve().with_name("deployer-parameters.json")
        if parameters_json_path.exists():
            try:
                with parameters_json_path.open("r") as parameters_json_file:
                    parameters_dict = json.load(parameters_json_file)
                print(f"The parameters json file give the following parameters: {parameters_dict}")
            except (OSError, json.JSONDecodeError) as json_exception:
                print(f"The parameters json file can't be read: {json_exception}")
    else:
        print("The script is running in a normal Python process")
        this_script_dir_path = Path(__file__).parent.absolute()

    print(f"The script parent path is '{this_script_dir_path}'\n")

    # Set umask for folder and file creation
    new_mask = 0o000
    old_umask = os.umask(new_mask)

    # Commands requested by the script arguments

    def build_pel(parsed_args):
        working_folder_path = Path(parsed_args.workingFolderPath)
        templated_deployment_description_file_path = Path(parsed_args.templatedDeploymentDescriptionFile)
        if parsed_args.componentConfigFolder == "None":
            component_config_folder_path = None
        else:
            component_config_folder_path = Path(parsed_args.componentConfigFolder)
        deployment_description_file_path = Path(parsed_args.pelDeploymentDescriptionFile)

        print(f" - The deployer arguments are:")
        print(f"     - The deployer working folder is '{working_folder_path}'")
        print(f"     - The templated deployment description json file is '{templated_deployment_description_file_path}'")
        print(f"     - The component config folder is '{component_config_folder_path}'")
        print(f"     - The resulting deployment description json file is '{deployment_description_file_path}'")

        deployment_description_builder = DeploymentDescriptionBuilder(component_config_folder_path)
        deployment_description_builder.parse_deployment_description_from_json_file_to_json_file(templated_deployment_description_file_path, "pel", deployment_description_file_path)

        return 0

    def deploy_pel(parsed_args, deploy_and_start=False):
        working_folder_path = Path(parsed_args.workingFolderPath)
        deployment_description_file_path = Path(parsed_args.pelDeploymentDescriptionFile)
        component_config_folder_path = Path(parsed_args.componentConfigFolder)
        component_tgz_folder_path = Path(parsed_args.componentTgzFolder)

        print(f" - The deployer arguments are:")
        print(f"     - The deployer working folder is '{working_folder_path}'")
        print(f"     - The deployment description json file is '{deployment_description_file_path}'")
        print(f"     - The component config folder is '{component_config_folder_path}'")
        print(f"     - The component tgz folder is '{component_tgz_folder_path}'")

        pel_deployer = PelDeployer(working_folder_path, component_config_folder_path, component_tgz_folder_path)
        pel_deployer.deploy_from_deployment_description_json_file(deployment_description_file_path, remove_start_and_docker_loop_from_equinox_sh=not deploy_and_start)

        if not deploy_and_start:
            parsed_args.componentDeploymentPath = []    # stop_pel expects this argument
            stop_pel(parsed_args, make_copy_of_databases_root_folder=True)
        return 0

    def deploy_and_start_pel(parsed_args):
        deploy_pel(parsed_args, deploy_and_start=True)
        return 0

    def _get_pel_running(parsed_args):
        working_folder_path = Path(parsed_args.workingFolderPath)

        print(f" - The deployer arguments are:")
        print(f"     - The deployer working folder is '{working_folder_path}'")

        return PelRunning(working_folder_path)

    def start_pel(parsed_args):
        pel_running = _get_pel_running(parsed_args)

        component_deployment_path = None
        if len(parsed_args.componentDeploymentPath) > 0:
            component_deployment_path = parsed_args.componentDeploymentPath[0]
            print(f"     - The component to start is '{component_deployment_path}'")

        pel_running.start(component_deployment_path)
        return 0

    def stop_pel(parsed_args, make_copy_of_databases_root_folder=False):
        pel_running = _get_pel_running(parsed_args)

        component_deployment_path = None
        if len(parsed_args.componentDeploymentPath) > 0:
            component_deployment_path = parsed_args.componentDeploymentPath[0]
            print(f"     - The component to stop is '{component_deployment_path}'")

        pel_running.stop(component_deployment_path)
        if make_copy_of_databases_root_folder:
            pel_running.copy_working_databases_data_root_folder_as_original()
        return 0

    def build_single_dsl_pel(parsed_args):
        pel_running = _get_pel_running(parsed_args)

        print(f"     - The DSL log XML trace level to use is '{parsed_args.dslLogXmlTraceLevel}'")
        print(f"     - The DSL log XML max log file size to use is '{parsed_args.dslLogXmlMaxLogFileSize}'")

        pel_running.build_single_dsl_pel(parsed_args.dslLogXmlTraceLevel, parsed_args.dslLogXmlMaxLogFileSize)
        return 0

    def start_single_dsl_pel(parsed_args):
        pel_running = _get_pel_running(parsed_args)
        pel_running.start_single_dsl_pel()
        return 0

    def stop_single_dsl_pel(parsed_args):
        pel_running = _get_pel_running(parsed_args)
        pel_running.stop_single_dsl_pel()
        return 0

    def restore_pel_databases(parsed_args):
        pel_running = _get_pel_running(parsed_args)
        pel_running.restore_working_databases_data_root_folder_from_original()
        return 0

    def test_pel(parsed_args):
        pel_running = _get_pel_running(parsed_args)

        cataclysm_folder_path = Path(parsed_args.cataclysmFolder)
        print(f"     - The cataclysm folder is '{cataclysm_folder_path}'")
        print(f"     - The test profile is '{parsed_args.testProfile}'")

        test_name_to_run = None
        if len(parsed_args.testName) > 0:
            test_name_to_run = parsed_args.testName[0]
            print(f"     - The test name to run is '{test_name_to_run}'")

        pel_running.test(cataclysm_folder_path, parsed_args.testProfile, test_name_to_run)
        return 0

    def build_pil(parsed_args):
        working_folder_path = Path(parsed_args.workingFolderPath)
        templated_deployment_description_file_path = Path(parsed_args.templatedDeploymentDescriptionFile)
        if parsed_args.componentConfigFolder == "None":
            component_config_folder_path = None
        else:
            component_config_folder_path = Path(parsed_args.componentConfigFolder)
        deployment_description_file_path = Path(parsed_args.pilDeploymentDescriptionFile)

        print(f" - The deployer arguments are:")
        print(f"     - The deployer working folder is '{working_folder_path}'")
        print(f"     - The templated deployment description json file is '{templated_deployment_description_file_path}'")
        print(f"     - The component config folder is '{component_config_folder_path}'")
        print(f"     - The resulting deployment description json file is '{deployment_description_file_path}'")

        deployment_description_builder = DeploymentDescriptionBuilder(component_config_folder_path)
        deployment_description_builder.parse_deployment_description_from_json_file_to_json_file(templated_deployment_description_file_path, "pil", deployment_description_file_path)

        return 0

    def deploy_pil(parsed_args):
        working_folder_path = Path(parsed_args.workingFolderPath)
        deployment_description_file_path = Path(parsed_args.pilDeploymentDescriptionFile)

        print(f" - The deployer arguments are:")
        print(f"     - The deployer working folder is '{working_folder_path}'")
        print(f"     - The deployment description json file is '{deployment_description_file_path}'")

        pil_deployer = PilDeployer(working_folder_path)
        pil_deployer.deploy_from_deployment_description_json_file(deployment_description_file_path)
        return 0

    def save_the_basic_docker_images_used_by_the_pil(parsed_args):
        working_folder_path = Path(parsed_args.workingFolderPath)

        print(f" - The deployer arguments are:")
        print(f"     - The deployer working folder is '{working_folder_path}'")

        pil_running = PilRunning(working_folder_path)
        pil_running.save_the_basic_docker_images_used()
        return 0

    def load_the_basic_docker_images_used_by_the_pil(parsed_args):
        working_folder_path = Path(parsed_args.workingFolderPath)
        docker_images_tar_gz_file_path = Path(parsed_args.dockerImagesTarGzFilePath[0])

        print(f" - The deployer arguments are:")
        print(f"     - The deployer working folder is '{working_folder_path}'")
        print(f"     - The tar.gz file to load is '{docker_images_tar_gz_file_path}'")
        print(f"     - The 'do not check hash' status is '{parsed_args.doNotCheckHash}'")

        pil_running = PilRunning(working_folder_path)
        pil_running.load_the_basic_docker_images_to_used(docker_images_tar_gz_file_path, do_not_check_the_used_components_hash=parsed_args.doNotCheckHash)
        return 0

    def remove_the_basic_docker_images_used_by_the_pil(parsed_args):
        working_folder_path = Path(parsed_args.workingFolderPath)

        print(f" - The deployer arguments are:")
        print(f"     - The deployer working folder is '{working_folder_path}'")

        pil_running = PilRunning(working_folder_path)
        pil_running.remove_the_basic_docker_images_used()
        return 0

    def start_pil(parsed_args):
        working_folder_path = Path(parsed_args.workingFolderPath)

        print(f" - The deployer arguments are:")
        print(f"     - The deployer working folder is '{working_folder_path}'")
        print(f"     - The keeping intermediate images status is '{parsed_args.keepTheIntermediateImages}'")

        pil_running = PilRunning(working_folder_path)
        pil_running.start(keep_the_intermediate_images=parsed_args.keepTheIntermediateImages)
        return 0

    def get_logs_pil(parsed_args):
        working_folder_path = Path(parsed_args.workingFolderPath)

        print(f" - The deployer arguments are:")
        print(f"     - The deployer working folder is '{working_folder_path}'")

        pil_running = PilRunning(working_folder_path)
        pil_running.logs()
        return 0

    def stop_pil(parsed_args):
        working_folder_path = Path(parsed_args.workingFolderPath)

        print(f" - The deployer arguments are:")
        print(f"     - The deployer working folder is '{working_folder_path}'")
        print(f"     - The keeping intermediate images status is '{parsed_args.keepTheIntermediateImages}'")
        print(f"     - The 'do not get logs' status is '{parsed_args.doNotGetLogs}'")

        pil_running = PilRunning(working_folder_path)
        pil_running.stop(keep_the_intermediate_images=parsed_args.keepTheIntermediateImages, do_not_get_logs=parsed_args.doNotGetLogs)
        return 0

    # Default script arguments values by destination parameter name
    default_working_folder_path = this_script_dir_path / "deployer-working-folder"
    default_templated_deployment_description_file = this_script_dir_path / "deployment-template.json"
    default_deployment_description_base_file_name = "deployment-description.json"
    default_pel_deployment_description_file = default_working_folder_path / f"pel-{default_deployment_description_base_file_name}"
    default_pil_deployment_description_file = default_working_folder_path / f"pil-{default_deployment_description_base_file_name}"
    args_default_value_by_destination_parameter_name = {
        "workingFolderPath": default_working_folder_path,
        "templatedDeploymentDescriptionFile": default_deployment_description_base_file_name,
        "pelDeploymentDescriptionFile": default_pel_deployment_description_file,
        "pilDeploymentDescriptionFile": default_pil_deployment_description_file,
        "dslLogXmlTraceLevel": "DEBUG",
        "dslLogXmlMaxLogFileSize": 10240000,
    }
    # Merge with frozen parameters
    args_default_value_by_destination_parameter_name.update(parameters_dict)

    # Special for build command as it is not mandatory
    default_component_config_folder_for_build_command = "None"
    if "componentConfigFolder" in args_default_value_by_destination_parameter_name:
        default_component_config_folder_for_build_command = args_default_value_by_destination_parameter_name["componentConfigFolder"]

    # Parse the script arguments
    common_parser = argparse.ArgumentParser(add_help=False)
    destination_parameter_name = "workingFolderPath"
    common_parser.add_argument("--working-folder", dest=destination_parameter_name, type=str,
                               help=f"Deployer working directory, by default '{args_default_value_by_destination_parameter_name[destination_parameter_name]}'",
                               default=args_default_value_by_destination_parameter_name[destination_parameter_name])

    common_pel_deployment_parser = argparse.ArgumentParser(add_help=False)
    destination_parameter_name = "pelDeploymentDescriptionFile"
    common_pel_deployment_parser.add_argument(dest=destination_parameter_name, metavar='DEPLOYMENT-JSON-FILE', type=str, nargs="?",
                                              help=f"PEL deployment description json file, by default {args_default_value_by_destination_parameter_name[destination_parameter_name]}",
                                              default=args_default_value_by_destination_parameter_name[destination_parameter_name])
    destination_parameter_name = "componentConfigFolder"
    if destination_parameter_name in args_default_value_by_destination_parameter_name:
        common_pel_deployment_parser.add_argument("--component-config-folder", dest=destination_parameter_name, type=str,
                                                  help=f"Component config file directory ('[gan project]/config'), by default {args_default_value_by_destination_parameter_name[destination_parameter_name]}",
                                                  default=args_default_value_by_destination_parameter_name[destination_parameter_name])
    else:
        common_pel_deployment_parser.add_argument("--component-config-folder", dest=destination_parameter_name, type=str, required=True,
                                                  help=f"Component config file directory ('[gan project]/config')")
    destination_parameter_name = "componentTgzFolder"
    if destination_parameter_name in args_default_value_by_destination_parameter_name:
        common_pel_deployment_parser.add_argument("--component-tgz-folder", dest=destination_parameter_name, type=str,
                                                  help=f"Component tgz file directory ('[gan project]/target/distrib'), by default {args_default_value_by_destination_parameter_name[destination_parameter_name]}",
                                                  default=args_default_value_by_destination_parameter_name[destination_parameter_name])
    else:
        common_pel_deployment_parser.add_argument("--component-tgz-folder", dest=destination_parameter_name, type=str, required=True,
                                                  help=f"Component tgz file directory ('[gan project]/target/distrib')")

    # noinspection PyTypeChecker
    parser = argparse.ArgumentParser(description="Deployer",
                                     usage="The deployer allows:\n   "
                                           "      - build a deployment description file from a template description file\n"
                                           "         - deploy as specified by this deployment description file\n"
                                           "         - start and stop this deployment\n"
                                           "\n"
                                           "       And this for several target deployments: PEL and PIL.\n"
                                           "\n"
                                           "       For the PEL target, it allows to build a 'single DSL' deployment from\n"
                                           "       the standard PEL deployment and to start/stop it.\n"
                                           "\n"
                                           "       Description template --build[target]--> Final description --deploy--> Deployment result based on target"
                                           "\n"
                                           "       From the PEL stage deployed --build-single-dsl-pel--> Single DSL deployment"
                                           "\n"
                                           "       If you choose the 'deploy-and-start-pel' option, there is no initial copy of the database,\n"
                                           "       so you cannot use the 'restore-pel' option to restore the database contents to its initial state."
                                           "\n",
                                     epilog="You can use one of the above commands with '--help' to get specific information, for example 'build --help'.",
                                     formatter_class=lambda prog: argparse.RawTextHelpFormatter(prog, width=150, max_help_position=150))

    subparsers = parser.add_subparsers(help="", dest="subparser_name", metavar="")

    help_string = "Build the PEL deployment description json file from templated description json file."
    subparser = subparsers.add_parser("build-pel", parents=[common_parser],
                                      description=help_string,
                                      help=help_string)
    destination_parameter_name = "templatedDeploymentDescriptionFile"
    subparser.add_argument(dest=destination_parameter_name, metavar='TEMPLATE-DEPLOYMENT-JSON-FILE', type=str, nargs="?",
                           help=f"Template deployment description json file, by default {args_default_value_by_destination_parameter_name[destination_parameter_name]}",
                           default=args_default_value_by_destination_parameter_name[destination_parameter_name])
    destination_parameter_name = "componentConfigFolder"
    subparser.add_argument("--component-config-folder", dest=destination_parameter_name, type=str,
                           help=f"Component config file directory ('[gan project]/config'), by default '{default_component_config_folder_for_build_command}'. 'None' to avoid using the equinox.sh parameter check",
                           default=default_component_config_folder_for_build_command)
    destination_parameter_name = "pelDeploymentDescriptionFile"
    subparser.add_argument("--deployment-description-result-file", dest=destination_parameter_name, metavar='DEPLOYMENT-JSON-FILE', type=str,
                           help=f"PEL deployment description result json file, by default {args_default_value_by_destination_parameter_name[destination_parameter_name]}",
                           default=args_default_value_by_destination_parameter_name[destination_parameter_name])
    subparser.set_defaults(func=build_pel)

    help_string = "Make a PEL deployment from description json file."
    subparser = subparsers.add_parser("deploy-pel", parents=[common_parser, common_pel_deployment_parser],
                                      description=help_string,
                                      help=help_string)
    subparser.set_defaults(func=deploy_pel)

    help_string = "Make a PEL deployment from description json file and start it."
    subparser = subparsers.add_parser("deploy-and-start-pel", parents=[common_parser, common_pel_deployment_parser],
                                      description=help_string,
                                      help=help_string)
    subparser.set_defaults(func=deploy_and_start_pel)

    help_string = "Start PEL deployment."
    subparser = subparsers.add_parser("start-pel", parents=[common_parser],
                                      description=help_string,
                                      help=help_string)
    subparser.add_argument(dest="componentDeploymentPath", metavar='COMPONENT_DEPLOYMENT_PATH', type=str, nargs="*",
                           help=f"Component deployment path to the component to start, by default all components are started")
    subparser.set_defaults(func=start_pel)

    help_string = "Stop PEL deployment."
    subparser = subparsers.add_parser("stop-pel", parents=[common_parser],
                                      description=help_string,
                                      help=help_string)
    subparser.add_argument(dest="componentDeploymentPath", metavar='COMPONENT_DEPLOYMENT_PATH', type=str, nargs="*",
                           help=f"Component deployment path to the component to stop, by default all components are started")
    subparser.set_defaults(func=stop_pel)

    help_string = "Build a single DSL PEL from an existing PEL deployment."
    subparser = subparsers.add_parser("build-single-dsl-pel", parents=[common_parser],
                                      description=help_string,
                                      help=help_string)
    destination_parameter_name = "dslLogXmlTraceLevel"
    subparser.add_argument("--dsl-log-xml-trace-level", dest=destination_parameter_name, type=str,
                           help=f"DSLs log4j.xml trace level, by default '{args_default_value_by_destination_parameter_name[destination_parameter_name]}'",
                           default=args_default_value_by_destination_parameter_name[destination_parameter_name])
    destination_parameter_name = "dslLogXmlMaxLogFileSize"
    subparser.add_argument("--dsl-log-xml-max-log-file-size", dest=destination_parameter_name, type=int,
                           help=f"DSLs log4j.xml max log file size, by default {args_default_value_by_destination_parameter_name[destination_parameter_name]}",
                           default=args_default_value_by_destination_parameter_name[destination_parameter_name])
    subparser.set_defaults(func=build_single_dsl_pel)

    help_string = "Start a single DSL PEL."
    subparser = subparsers.add_parser("start-single-dsl-pel", parents=[common_parser],
                                      description=help_string,
                                      help=help_string)
    subparser.set_defaults(func=start_single_dsl_pel)

    help_string = "Stop a single DSL PEL."
    subparser = subparsers.add_parser("stop-single-dsl-pel", parents=[common_parser],
                                      description=help_string,
                                      help=help_string)
    subparser.set_defaults(func=stop_single_dsl_pel)

    help_string = "Restore the PEL databases data as original if it is existing."
    subparser = subparsers.add_parser("restore-pel", parents=[common_parser],
                                      description=help_string,
                                      help=help_string)
    subparser.set_defaults(func=restore_pel_databases)

    help_string = "Test PEL deployment."
    subparser = subparsers.add_parser("test-pel", parents=[common_parser],
                                      description=help_string,
                                      help=help_string)
    destination_parameter_name = "cataclysmFolder"
    if destination_parameter_name in args_default_value_by_destination_parameter_name:
        subparser.add_argument("--cataclysm-folder", dest=destination_parameter_name, type=str,
                               help=f"Cataclysm directory ('cataclysm-[gan project]'), by default {args_default_value_by_destination_parameter_name[destination_parameter_name]}",
                               default=args_default_value_by_destination_parameter_name[destination_parameter_name])
    else:
        subparser.add_argument("--cataclysm-folder", dest=destination_parameter_name, type=str, required=True,
                               help=f"Cataclysm directory ('cataclysm-[gan project]')")
    destination_parameter_name = "testProfile"
    if destination_parameter_name in args_default_value_by_destination_parameter_name:
        subparser.add_argument("--test-profile", dest=destination_parameter_name, type=str,
                               help=f"Test profile, by default {args_default_value_by_destination_parameter_name[destination_parameter_name]}",
                               default=args_default_value_by_destination_parameter_name[destination_parameter_name])
    else:
        subparser.add_argument("--test-profile", dest=destination_parameter_name, type=str, required=True,
                               help=f"Test profile")
    subparser.add_argument(dest="testName", metavar='TEST_NAME', type=str, nargs="*",
                           help=f"Test name to run ('[class name]' or '[class name]#[test name]'), by default all tests are launched")
    subparser.set_defaults(func=test_pel)

    help_string = "Build the PIL deployment description json file from templated description json file."
    subparser = subparsers.add_parser("build-pil", parents=[common_parser],
                                      description=help_string,
                                      help=help_string)
    destination_parameter_name = "templatedDeploymentDescriptionFile"
    subparser.add_argument(dest=destination_parameter_name, metavar='TEMPLATED-DEPLOYMENT-JSON-FILE', type=str, nargs="?",
                           help=f"Templated deployment description json file, by default {args_default_value_by_destination_parameter_name[destination_parameter_name]}",
                           default=args_default_value_by_destination_parameter_name[destination_parameter_name])
    destination_parameter_name = "componentConfigFolder"
    subparser.add_argument("--component-config-folder", dest=destination_parameter_name, type=str,
                           help=f"Component config file directory ('[gan project]/config'), by default '{default_component_config_folder_for_build_command}'. 'None' to avoid using the equinox.sh parameter check",
                           default=default_component_config_folder_for_build_command)
    destination_parameter_name = "pilDeploymentDescriptionFile"
    subparser.add_argument("--deployment-description-result-file", dest=destination_parameter_name, metavar='DEPLOYMENT-JSON-FILE', type=str,
                           help=f"PIL deployment description result json file, by default {args_default_value_by_destination_parameter_name[destination_parameter_name]}",
                           default=args_default_value_by_destination_parameter_name[destination_parameter_name])
    subparser.set_defaults(func=build_pil)

    help_string = "Make a PIL deployment from description json file."
    subparser = subparsers.add_parser("deploy-pil", parents=[common_parser],
                                      description=help_string,
                                      help=help_string)
    destination_parameter_name = "pilDeploymentDescriptionFile"
    subparser.add_argument(dest=destination_parameter_name, metavar='DEPLOYMENT-JSON-FILE', type=str, nargs="?",
                           help=f"PIL deployment description json file, by default {args_default_value_by_destination_parameter_name[destination_parameter_name]}",
                           default=args_default_value_by_destination_parameter_name[destination_parameter_name])
    subparser.set_defaults(func=deploy_pil)

    help_string = "Start PIL deployment."
    subparser = subparsers.add_parser("start-pil", parents=[common_parser],
                                      description=help_string,
                                      help=help_string)
    subparser.add_argument("--keep-the-intermediate-images", dest="keepTheIntermediateImages", action="store_true",
                           help=f"Keep the intermediate images, by default False")
    subparser.set_defaults(func=start_pil)

    help_string = "Get running containers logs from PIL."
    subparser = subparsers.add_parser("get-logs-pil", parents=[common_parser],
                                      description=help_string,
                                      help=help_string)
    subparser.set_defaults(func=get_logs_pil)

    help_string = "Stop PIL deployment."
    subparser = subparsers.add_parser("stop-pil", parents=[common_parser],
                                      description=help_string,
                                      help=help_string)
    subparser.add_argument("--keep-the-intermediate-images", dest="keepTheIntermediateImages", action="store_true",
                           help=f"Keep the intermediate images, by default False")
    subparser.add_argument("--do-not-get-logs", dest="doNotGetLogs", action="store_true",
                           help=f"Do not get container logs before shutting down, by default False")
    subparser.set_defaults(func=stop_pil)

    help_string = "Save the basic docker images used by the PIL"
    subparser = subparsers.add_parser("save-the-basic-docker-images-used-by-the-pil", parents=[common_parser],
                                      description=help_string,
                                      help=help_string)
    subparser.set_defaults(func=save_the_basic_docker_images_used_by_the_pil)

    help_string = "Load the basic docker images used by the PIL"
    subparser = subparsers.add_parser("load-the-basic-docker-images-used-by-the-pil", parents=[common_parser],
                                      description=help_string,
                                      help=help_string)
    destination_parameter_name = "dockerImagesTarGzFilePath"
    subparser.add_argument(dest=destination_parameter_name, metavar='DOCKER-IMAGES-TAR-GZ-FILE', type=str, nargs=1,
                           help=f"Docker images tar.gz file to load")
    subparser.add_argument("--do-not-check-hash", dest="doNotCheckHash", action="store_true",
                           help=f"Do not check the components hash used by the PIL, by default False")
    subparser.set_defaults(func=load_the_basic_docker_images_used_by_the_pil)

    help_string = "Remove the basic docker images used by the PIL"
    subparser = subparsers.add_parser("remove-the-basic-docker-images-used-by-the-pil", parents=[common_parser],
                                      description=help_string,
                                      help=help_string)
    subparser.set_defaults(func=remove_the_basic_docker_images_used_by_the_pil)

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()
    # noinspection PyBroadException
    try:
        status_code = args.func(args)
        sys.exit(status_code)
    except Exception as args_function_exception:
        print("Exception: ", traceback.format_exc())
        print("-----------------------------------")
        parser.print_help()
        sys.exit(1)
