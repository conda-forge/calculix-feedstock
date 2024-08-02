cd ccx*/src
del Makefile_MT
copy %RECIPE_DIR%\Makefile_MT Makefile_MT
copy %BUILD_PREFIX%\Library\mingw-w64\bin\mingw32-make %BUILD_PREFIX%\Library\mingw-w64\bin\make


rem this line translates the windows-paths to paths understandable for the mingw env
rem -m, --mixed           like --windows, but with regular slashes (C:/WINNT)
for /F "delims=\" %%i IN ('cygpath.exe -m "%LIBRARY_PREFIX%"') DO set "LIBRARY_PREFIX=%%i"

make -f Makefile_MT ^
    SPOOLES_INCLUDE_DIR="%LIBRARY_PREFIX%/mingw-w64/include/spooles" ^
    LIB_DIR="%LIBRARY_PREFIX%/mingw-w64/lib" ^
    LDFLAGS="-L%LIBRARY_PREFIX%/mingw-w64/lib -L%LIBRARY_PREFIX%/lib"^
    FC="gfortran" ^
    VERSION="%PKG_VERSION%"

rem adding .exe to make the file executable
move ccx_*_conda "%LIBRARY_PREFIX%\bin\ccx.exe"
cd %SRC_DIR%
