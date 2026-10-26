cmake_minimum_required(VERSION 3.16)
project(uqu_perfsim LANGUAGES CXX)
set(ETISS_DISABLE_COMPILERFLAGS ON)
find_package(ETISS CONFIG REQUIRED HINTS "${ETISS_ROOT}/lib/CMake/ETISS")
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(SWEVAL "${PERFSIM_ROOT}/etiss-perf-sim/etiss_plugins/SoftwareEvalLib")
set(BACKENDS "${SWEVAL}/libs/backends")
include("${GENERATED_DIR}/models.cmake")
add_executable(uqu_perfsim
  driver.cpp uqu_blocks_runtime.cpp "${GENERATED_DIR}/registry.cpp" ${MODEL_SOURCES}
  "${BACKENDS}/src/internal/PerformanceModel.cpp"
  "${SWEVAL}/libs/monitors/src/Monitor.cpp" "${SWEVAL}/src/TracerPlugin.cpp")
target_include_directories(uqu_perfsim PRIVATE
  . ${MODEL_MAP_INCLUDES} "${ETISS_INCLUDE_DIRS}" "${BACKENDS}/include/internal"
  "${BACKENDS}/include/api" "${BACKENDS}/include/api/softwareEval-backends"
  "${SWEVAL}/include/SoftwareEval" "${SWEVAL}/libs/monitors/include"
  "${SWEVAL}/libs/monitors/include/monitors"
  "${CMAKE_CURRENT_SOURCE_DIR}/../models" ${MODEL_INCLUDES})
target_link_libraries(uqu_perfsim PRIVATE ${ETISS_LIBRARIES} Threads::Threads dl)
target_link_options(uqu_perfsim PRIVATE -rdynamic)
# The pinned upstream Channel.h uses uint64_t before including <cstdint>.
target_compile_options(uqu_perfsim PRIVATE -include cstdint)
