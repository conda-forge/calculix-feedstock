cd ccx*/src
del Makefile_MT
copy %RECIPE_DIR%\Makefile_MT Makefile_MT


rem this line translates the windows-paths to paths understandable for the mingw env
rem -m, --mixed           like --windows, but with regular slashes (C:/WINNT)

make -f Makefile_MT ^
    SPOOLES_INCLUDE_DIR="%LIBRARY_PREFIX%/include/spooles" ^
    LIB_DIR="%LIBRARY_PREFIX%/lib" ^
    LDFLAGS="-L%LIBRARY_PREFIX%/lib"^
    FC="%FC%" ^
    VERSION="%PKG_VERSION%"

if errorlevel 1 exit 1

rem adding .exe to make the file executable
move ccx_*_conda "%LIBRARY_PREFIX%\bin\ccx.exe"
cd %SRC_DIR%

if errorlevel 1 exit 1