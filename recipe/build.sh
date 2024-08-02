cd ccx*/src
rm Makefile_MT
cp ${RECIPE_DIR}/Makefile_MT Makefile_MT
if [[ ${HOST} =~ .*linux.* ]]; then
	export LDFLAGS="${LDFLAGS} -lrt"
fi

if [[ ${target_platform} != osx-64 ]]; then
    export FFLAGS="${FFLAGS} ${LDFLAGS} -fallow-argument-mismatch"
fi

if [[ ${target_platform} == osx-* ]]; then
  export CFLAGS="${CFLAGS} -Wno-error=implicit-function-declaration"
fi

make -f Makefile_MT \
    SPOOLES_INCLUDE_DIR="${PREFIX}/include/spooles" \
    LIB_DIR="${PREFIX}/lib" \
    VERSION="${PKG_VERSION}" -j${CPU_COUNT}

mkdir -p ${PREFIX}/bin
cp ccx_*_conda ${PREFIX}/bin/ccx
cd $SRC_DIR
