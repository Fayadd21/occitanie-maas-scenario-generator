import datetime
import json
import os
import shutil
import subprocess as sp


def configure(context):
    context.config("git_binary", "git")
    context.config("output_path")
    context.config("output_prefix", "ile_de_france_")

    for option in ("sampling_rate", "hts", "random_seed"):
        context.config(option)


def get_version():
    version_path = os.path.dirname(os.path.realpath(__file__))
    version_path = os.path.realpath("{}/../version.txt".format(version_path))

    with open(version_path) as f:
        return f.read().strip()


def _git_run(context, arguments=None, cwd=None, catch_output=False):
    if cwd is None:
        cwd = context.path()

    git_binary = shutil.which(context.config("git_binary"))
    command_line = [git_binary] + (arguments or [])

    if catch_output:
        return sp.check_output(command_line, cwd=cwd).decode("utf-8").strip()

    return_code = sp.check_call(command_line, cwd=cwd)
    if return_code != 0:
        raise RuntimeError("Git return code: %d" % return_code)


def get_commit(context):
    root_path = os.path.dirname(os.path.realpath(__file__))
    root_path = os.path.realpath("{}/..".format(root_path))

    try:
        return _git_run(context, ["rev-parse", "HEAD"], cwd=root_path, catch_output=True)
    except sp.CalledProcessError:
        return "unknown"


def execute(context):
    information = dict(
        sampling_rate=context.config("sampling_rate"),
        hts=context.config("hts"),
        random_seed=context.config("random_seed"),
        created=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        version=get_version(),
        commit=get_commit(context),
    )

    with open("%s/%smeta.json" % (context.config("output_path"), context.config("output_prefix")), "w+") as f:
        json.dump(information, f, indent=4)


def validate(context):
    git_binary = shutil.which(context.config("git_binary"))
    if git_binary in ("", None):
        raise RuntimeError("Cannot find git binary at: %s" % context.config("git_binary"))

    if b"2." not in sp.check_output([git_binary, "--version"], stderr=sp.STDOUT):
        print("WARNING! Git of at least version 2.x.x is recommended!")

    return get_version() + get_commit(context)
