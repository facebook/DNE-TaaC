// Copyright (c) Meta Platforms, Inc. and affiliates.

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

extern struct _inittab tictaac_builtin_modules[];

static const char ENTRY_POINT_SOURCE[] =
    "import taac.runner.tictaac_oss\n"
    "taac.runner.tictaac_oss.main()\n";

static const int EXIT_LAUNCHER_FAILURE = 120;
static const char OSS_MODE_VARIABLE[] = "TAAC_OSS";
static const char OSS_MODE_ENABLED[] = "1";
static const int KEEP_CALLER_VALUE = 0;

static int fail_status(PyStatus status) {
  if (PyStatus_IsExit(status)) {
    return status.exitcode;
  }
  Py_ExitStatusException(status);
  return EXIT_LAUNCHER_FAILURE;
}

static int resolve_executable_path(char* buffer, size_t capacity) {
  ssize_t length = readlink("/proc/self/exe", buffer, capacity - 1);
  if (length < 0 || (size_t)length >= capacity - 1) {
    return -1;
  }
  buffer[length] = '\0';
  return 0;
}

static PyStatus preinitialize(void) {
  PyPreConfig preconfig;
  PyPreConfig_InitIsolatedConfig(&preconfig);
  preconfig.utf8_mode = 1;
  return Py_PreInitialize(&preconfig);
}

static PyStatus initialize(int argc, char** argv, const char* executable_path) {
  PyConfig config;
  PyConfig_InitIsolatedConfig(&config);

  PyStatus status =
      PyConfig_SetBytesString(&config, &config.executable, executable_path);
  if (PyStatus_Exception(status)) {
    goto done;
  }
  status =
      PyConfig_SetBytesString(&config, &config.program_name, executable_path);
  if (PyStatus_Exception(status)) {
    goto done;
  }
  status = PyConfig_SetBytesArgv(&config, argc, argv);
  if (PyStatus_Exception(status)) {
    goto done;
  }
  status =
      PyConfig_SetBytesString(&config, &config.run_command, ENTRY_POINT_SOURCE);
  if (PyStatus_Exception(status)) {
    goto done;
  }

  wchar_t* payload_path = Py_DecodeLocale(executable_path, NULL);
  if (payload_path == NULL) {
    status = PyStatus_NoMemory();
    goto done;
  }
  config.module_search_paths_set = 1;
  status = PyWideStringList_Append(&config.module_search_paths, payload_path);
  PyMem_RawFree(payload_path);
  if (PyStatus_Exception(status)) {
    goto done;
  }

  config.parse_argv = 0;
  config.site_import = 0;
  config.write_bytecode = 0;
  config.user_site_directory = 0;
  config.install_signal_handlers = 1;

  status = Py_InitializeFromConfig(&config);

done:
  PyConfig_Clear(&config);
  return status;
}

int main(int argc, char** argv) {
  char executable_path[PATH_MAX];
  if (resolve_executable_path(executable_path, sizeof(executable_path)) != 0) {
    perror("tictaac: cannot resolve /proc/self/exe");
    return EXIT_LAUNCHER_FAILURE;
  }

  if (setenv(OSS_MODE_VARIABLE, OSS_MODE_ENABLED, KEEP_CALLER_VALUE) != 0) {
    perror("tictaac: cannot set TAAC_OSS");
    return EXIT_LAUNCHER_FAILURE;
  }

  if (PyImport_ExtendInittab(tictaac_builtin_modules) != 0) {
    fprintf(stderr, "tictaac: cannot register builtin modules\n");
    return EXIT_LAUNCHER_FAILURE;
  }

  PyStatus status = preinitialize();
  if (PyStatus_Exception(status)) {
    return fail_status(status);
  }
  status = initialize(argc, argv, executable_path);
  if (PyStatus_Exception(status)) {
    return fail_status(status);
  }

  return Py_RunMain();
}
