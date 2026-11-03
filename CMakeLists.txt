cmake_minimum_required(VERSION 3.21)

project(PlanetDatabase VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

find_package(Qt6 6.5 REQUIRED COMPONENTS Core Gui OpenGL Quick QuickControls2 Widgets)

qt_add_executable(PlanetDatabase
    main.cpp
    GalaxyView.cpp
    GalaxyView.h
    ProjectStore.cpp
    ProjectStore.h
)

qt_add_qml_module(PlanetDatabase
    URI PlanetDatabase
    VERSION 1.0
    QML_FILES Main.qml
)

target_link_libraries(PlanetDatabase PRIVATE
    Qt6::Core
    Qt6::Gui
    Qt6::OpenGL
    Qt6::Quick
    Qt6::QuickControls2
    Qt6::Widgets
)

include(GNUInstallDirs)
install(TARGETS PlanetDatabase
    BUNDLE DESTINATION .
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)
