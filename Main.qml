import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import PlanetDatabase 1.0

ApplicationWindow {
    id: window
    visible: true
    width: 1440
    height: 900
    minimumWidth: 1050
    minimumHeight: 680
    title: "Planet Database"
    color: "#070b12"

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.preferredWidth: 292
            Layout.fillHeight: true
            color: "#0b111b"
            border.color: "#1a2635"
            border.width: 1

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 24
                spacing: 0

                RowLayout {
                    spacing: 12
                    Rectangle {
                        width: 34
                        height: 34
                        radius: 10
                        color: "#112b3a"
                        border.color: "#27627a"
                        Text {
                            anchors.centerIn: parent
                            text: "✦"
                            color: "#6de3f5"
                            font.pixelSize: 20
                        }
                    }
                    Column {
                        spacing: 2
                        Text {
                            text: "ORRERY"
                            color: "#e7f2fa"
                            font.pixelSize: 16
                            font.weight: Font.DemiBold
                            font.letterSpacing: 2.4
                        }
                        Text {
                            text: "GALACTIC ATLAS"
                            color: "#748699"
                            font.pixelSize: 9
                            font.letterSpacing: 1.6
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.topMargin: 26
                    Layout.bottomMargin: 24
                    height: 1
                    color: "#1c2938"
                }

                Text {
                    text: "PROJECT STORAGE"
                    color: "#75899d"
                    font.pixelSize: 10
                    font.weight: Font.DemiBold
                    font.letterSpacing: 1.3
                }
                Text {
                    Layout.topMargin: 10
                    Layout.fillWidth: true
                    text: projectStore.projectDirectory.length > 0
                          ? projectStore.projectDirectory
                          : "Choose a folder for your galaxy and discoveries."
                    color: projectStore.projectDirectory.length > 0 ? "#b9c9d8" : "#7c8b99"
                    font.pixelSize: 11
                    wrapMode: Text.WrapAnywhere
                    lineHeight: 1.25
                }
                Button {
                    Layout.fillWidth: true
                    Layout.topMargin: 14
                    text: projectStore.projectDirectory.length > 0
                          ? "CHANGE PROJECT FOLDER" : "CHOOSE PROJECT FOLDER"
                    onClicked: projectStore.chooseProjectFolder()
                    contentItem: Text {
                        text: parent.text
                        color: "#a9eaf4"
                        font.pixelSize: 10
                        font.weight: Font.DemiBold
                        font.letterSpacing: 0.6
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    background: Rectangle {
                        radius: 6
                        color: parent.down ? "#173344" : "#102330"
                        border.color: "#245267"
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.topMargin: 26
                    Layout.bottomMargin: 24
                    height: 1
                    color: "#1c2938"
                }

                Text {
                    text: "STAR RECORD"
                    color: "#75899d"
                    font.pixelSize: 10
                    font.weight: Font.DemiBold
                    font.letterSpacing: 1.3
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.topMargin: 12
                    implicitHeight: 124
                    radius: 8
                    color: "#0e1722"
                    border.color: "#1b2b3b"

                    Column {
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 7
                        Text {
                            text: galaxy.selectedStarIndex >= 0
                                  ? "CATALOG ID"
                                  : "NO STAR SELECTED"
                            color: "#8194a7"
                            font.pixelSize: 9
                            font.letterSpacing: 1.2
                        }
                        Text {
                            text: galaxy.selectedStarIndex >= 0
                                  ? "STAR-" + ("0000000" + (galaxy.selectedStarIndex + 1)).slice(-7)
                                  : "Click a star in the galaxy"
                            color: galaxy.selectedStarIndex >= 0 ? "#e5f3fa" : "#a1afbd"
                            font.pixelSize: 15
                            font.family: "Consolas"
                        }
                        Text {
                            text: galaxy.selectedStarIndex >= 0
                                  ? (projectStore.systems[galaxy.selectedStarIndex.toString()] || "Uncharted")
                                  : "Drag to pan · scroll to zoom"
                            color: "#6cdded"
                            font.pixelSize: 11
                            elide: Text.ElideRight
                            width: parent.width
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: 16
                    spacing: 8
                    visible: galaxy.selectedStarIndex >= 0
                    Text {
                        text: (projectStore.systems[galaxy.selectedStarIndex.toString()] || "").length > 0
                              ? "SYSTEM SAVED"
                              : "NAME THIS SYSTEM"
                        color: "#8194a7"
                        font.pixelSize: 9
                        font.letterSpacing: 1.2
                    }
                    TextField {
                        id: systemName
                        Layout.fillWidth: true
                        placeholderText: "e.g. The Far Lantern"
                        maximumLength: 80
                        enabled: projectStore.projectDirectory.length > 0
                                 && (projectStore.systems[galaxy.selectedStarIndex.toString()] || "").length === 0
                        color: "#e5f3fa"
                        placeholderTextColor: "#66798b"
                        leftPadding: 12
                        background: Rectangle {
                            radius: 6
                            color: "#0e1722"
                            border.color: systemName.activeFocus ? "#3d99ae" : "#243447"
                        }
                    }
                    Button {
                        Layout.fillWidth: true
                        text: "SAVE SYSTEM"
                        enabled: projectStore.projectDirectory.length > 0
                                 && (projectStore.systems[galaxy.selectedStarIndex.toString()] || "").length === 0
                                 && systemName.text.trim().length > 0
                        onClicked: {
                            if (projectStore.addSystem(galaxy.selectedStarIndex, systemName.text))
                                systemName.clear()
                        }
                        contentItem: Text {
                            text: parent.text
                            color: parent.enabled ? "#071016" : "#728392"
                            font.pixelSize: 10
                            font.weight: Font.DemiBold
                            font.letterSpacing: 1
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle {
                            radius: 6
                            color: parent.enabled ? "#69d5e7" : "#21303c"
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: projectStore.projectDirectory.length === 0
                        text: "Choose a project folder to save systems."
                        color: "#738496"
                        font.pixelSize: 10
                        wrapMode: Text.WordWrap
                    }
                }

                Item { Layout.fillHeight: true }

                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: "#1c2938"
                }
                Text {
                    Layout.topMargin: 14
                    text: "PROCEDURAL · SEED " + projectStore.seed.slice(0, 8).toUpperCase()
                    color: "#607486"
                    font.pixelSize: 9
                    font.letterSpacing: 0.6
                }
                Text {
                    text: "Galaxy data stays in your chosen folder."
                    color: "#607486"
                    font.pixelSize: 9
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: 22
            spacing: 16

            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                ColumnLayout {
                    spacing: 4
                    Text {
                        text: "MILKY WAY  /  LOCAL VOLUME"
                        color: "#6f879c"
                        font.pixelSize: 9
                        font.letterSpacing: 1.6
                    }
                    Text {
                        text: "Galaxy overview"
                        color: "#e4eef6"
                        font.pixelSize: 23
                        font.weight: Font.Medium
                    }
                }
                Item { Layout.fillWidth: true }
                Rectangle {
                    Layout.preferredWidth: 130
                    Layout.preferredHeight: 44
                    radius: 7
                    color: "#0d1722"
                    border.color: "#1c2a38"
                    Column {
                        anchors.centerIn: parent
                        spacing: 3
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: "STARS RENDERED"
                            color: "#71879a"
                            font.pixelSize: 8
                            font.letterSpacing: 0.8
                        }
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: "1,000,000"
                            color: "#c5e9f1"
                            font.pixelSize: 14
                            font.family: "Consolas"
                        }
                    }
                }
                Rectangle {
                    Layout.preferredWidth: 98
                    Layout.preferredHeight: 44
                    radius: 7
                    color: "#0d1722"
                    border.color: "#1c2a38"
                    Column {
                        anchors.centerIn: parent
                        spacing: 3
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: "VIEW ZOOM"
                            color: "#71879a"
                            font.pixelSize: 8
                            font.letterSpacing: 0.8
                        }
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: galaxy.zoom.toFixed(1) + "×"
                            color: "#c5e9f1"
                            font.pixelSize: 14
                            font.family: "Consolas"
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 10
                color: "#060a10"
                border.color: "#1a2734"
                clip: true

                GalaxyView {
                    id: galaxy
                    anchors.fill: parent
                    anchors.margins: 1
                    seed: projectStore.seed
                    starCount: projectStore.starCount
                }

                Rectangle {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.margins: 18
                    radius: 5
                    color: "#b00a131d"
                    border.color: "#283746"
                    width: legend.implicitWidth + 22
                    height: 30
                    Row {
                        id: legend
                        anchors.centerIn: parent
                        spacing: 8
                        Rectangle {
                            anchors.verticalCenter: parent.verticalCenter
                            width: 6
                            height: 6
                            radius: 3
                            color: "#6de3f5"
                        }
                        Text {
                            text: "PROCEDURAL STARFIELD"
                            color: "#91a4b4"
                            font.pixelSize: 8
                            font.letterSpacing: 1
                        }
                    }
                }

                Text {
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.margins: 18
                    text: "DRAG TO PAN     ·     SCROLL TO ZOOM     ·     CLICK A STAR"
                    color: "#728496"
                    font.pixelSize: 9
                    font.letterSpacing: 0.6
                }
            }

            Text {
                Layout.fillWidth: true
                visible: projectStore.lastError.length > 0
                text: projectStore.lastError
                color: "#ff9d9d"
                font.pixelSize: 11
                wrapMode: Text.WordWrap
            }
        }
    }
}
