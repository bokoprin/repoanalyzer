CPP_SOURCE_EXTENSIONS = {".c", ".cc", ".cpp", ".cxx"}
CPP_HEADER_EXTENSIONS = {".h", ".hh", ".hpp", ".hxx", ".inl", ".ipp"}
# Windows resource scripts are part of many C/C++ GUI projects.  They are
# not C++ translation units, but indexing them lets repoanalyzer connect
# menu/accelerator/dialog resource IDs back to command IDs safely.
CPP_RESOURCE_EXTENSIONS = {".rc", ".rc2"}
CPP_EXTENSIONS = CPP_SOURCE_EXTENSIONS | CPP_HEADER_EXTENSIONS | CPP_RESOURCE_EXTENSIONS
