import argparse
import os
from enum import Enum
from subprocess import call
from tempfile import NamedTemporaryFile

import attr

from dmpy.objects.dm_rule import DMRule


class SchedulingEngine(Enum):
    none = 0
    slurm = 1


def add_dm_args_to_argparse_object(object):
    object.add_argument("-r", "--run", action="store_true")
    object.add_argument("-j", "--jobs", type=int, default=1)
    object.add_argument("-c", "--no-cleanup", action="store_true")
    object.add_argument("--scheduler", default=SchedulingEngine.none.name)
    return object


def get_dm_arg_parser(description="dmpy powered analysis"):
    parser = argparse.ArgumentParser(description=description)
    parser = add_dm_args_to_argparse_object(parser)
    return parser


@attr.s(slots=True)
class DMBuilder(object):
    rules = attr.ib(attr.Factory(list))
    scheduler = attr.ib(default=SchedulingEngine.none)
    _targets = attr.ib(attr.Factory(set))

    def add(self, target, deps, cmds):
        if target in self._targets:
            raise Exception("Tried to add target twice: {}".format(target))
        self._targets.add(target)
        self.rules.append(DMRule(target, deps, cmds))

    def write_to_filehandle(self, fh):
        fh.write("SHELL := /bin/bash\n")
        for rule in self.rules:
            dirname = os.path.abspath(os.path.dirname(rule.target))

            fh.write("{}: {}\n".format(rule.target, ' '.join(rule.deps)))
            if self.scheduler == SchedulingEngine.slurm:
                cmd_prefix = 'srun '
            else:
                cmd_prefix = ''
            rule.recipe = [cmd_prefix + cmd for cmd in rule.recipe]
            rule.recipe.insert(0, "@test -d {0} || mkdir -p {0}".format(dirname))
            for cmd in rule.recipe:
                fh.write("\t{}\n".format(cmd))

        fh.write("all: {}\n".format(" ".join([r.target for r in self.rules])))
        fh.write(".DELETE_ON_ERROR:\n")
        fh.flush()


@attr.s(slots=True)
class DistributedMake(object):
    run = attr.ib(default=False)
    keep_going = attr.ib(default=False)
    jobs = attr.ib(default=1)
    no_cleanup = attr.ib(default=False)
    question = attr.ib(default=False)
    touch = attr.ib(default=False)
    debug = attr.ib(default=False)

    args_object = attr.ib(default=None)
    _makefile_fp = attr.ib(init=False)
    _dm_builder = attr.ib(attr.Factory(DMBuilder))

    def __attrs_post_init__(self):
        self._handle_args_object()

    def _handle_args_object(self):
        if self.args_object is None:
            return
        for attr_string in ['run', 'no_cleanup', 'jobs']:
            if attr_string in self.args_object:
                setattr(self, attr_string, getattr(self.args_object, attr_string))
        if "scheduler" in self.args_object:
            self._dm_builder.scheduler = SchedulingEngine[self.args_object.scheduler]

    def add(self, target, deps, commands):
        self._dm_builder.add(target, deps, commands)

    def execute(self):
        with NamedTemporaryFile(mode='wt', delete=not self.no_cleanup) as makefile_fp:
            self._dm_builder.write_to_filehandle(makefile_fp)

            makecmd = self.build_make_command(makefile_fp.name)

            print(" ".join(makecmd))
            return_code = call(" ".join(makecmd), shell=True)
            print(" ".join(makecmd))

        return return_code

    def build_make_command(self, makefile_name):
        makecmd = ["make"]
        if not self.run:
            makecmd.append("-n")
        if self.keep_going:
            makecmd.append("-k")
        if self.question:
            makecmd.append("-q {}".format(self.question))
        if self.touch:
            makecmd.append("-t {}".format(self.touch))
        if self.debug:
            makecmd.append("-d {}".format(self.debug))
        makecmd.append("-j {}".format(self.jobs))
        makecmd.append("-f {}".format(makefile_name))
        makecmd.append("all")
        return makecmd
