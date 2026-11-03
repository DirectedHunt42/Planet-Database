#include "GalaxyView.h"
#include "ProjectStore.h"

#include <QApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickWindow>
#include <QSGRendererInterface>
#include <QSurfaceFormat>

int main(int argc, char *argv[])
{
    QSurfaceFormat format;
    format.setRenderableType(QSurfaceFormat::OpenGL);
    format.setVersion(3, 3);
    format.setProfile(QSurfaceFormat::CoreProfile);
    format.setDepthBufferSize(0);
    QSurfaceFormat::setDefaultFormat(format);
    QQuickWindow::setGraphicsApi(QSGRendererInterface::OpenGL);

    QApplication app(argc, argv);
    QApplication::setApplicationName(QStringLiteral("Planet Database"));
    QApplication::setOrganizationName(QStringLiteral("Planet Database"));

    ProjectStore projectStore;
    QQmlApplicationEngine engine;
    engine.rootContext()->setContextProperty(QStringLiteral("projectStore"), &projectStore);
    engine.loadFromModule(QStringLiteral("PlanetDatabase"), QStringLiteral("Main"));

    if (engine.rootObjects().isEmpty())
        return -1;

    return app.exec();
}
