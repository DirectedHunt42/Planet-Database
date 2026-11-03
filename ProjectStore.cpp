#include "ProjectStore.h"

#include <QDir>
#include <QFile>
#include <QFileDialog>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRandomGenerator>
#include <QSaveFile>
#include <QByteArray>

namespace {

constexpr int projectFormatVersion = 1;
constexpr int galaxyStarCount = 1000000;
const QString projectFileName = QStringLiteral("planet-database.json");

}

ProjectStore::ProjectStore(QObject *parent)
    : QObject(parent),
      seed_(QRandomGenerator::global()->generate64())
{
}

QString ProjectStore::projectDirectory() const
{
    return projectDirectory_;
}

QString ProjectStore::seed() const
{
    return QString::number(seed_);
}

int ProjectStore::starCount() const
{
    return starCount_;
}

QString ProjectStore::lastError() const
{
    return lastError_;
}

QVariantMap ProjectStore::systems() const
{
    QVariantMap result;
    for (auto it = systems_.cbegin(); it != systems_.cend(); ++it)
        result.insert(QString::number(it.key()), it.value());
    return result;
}

void ProjectStore::chooseProjectFolder()
{
    const QString selectedPath = QFileDialog::getExistingDirectory(
        nullptr,
        QStringLiteral("Choose Galaxy Project Folder"),
        projectDirectory_);
    if (selectedPath.isEmpty())
        return;

    const QString filePath = QDir(selectedPath).filePath(projectFileName);
    quint64 candidateSeed = seed_;
    QHash<int, QString> candidateSystems;

    if (QFile::exists(filePath)) {
        QFile file(filePath);
        if (!file.open(QIODevice::ReadOnly)) {
            setError(QStringLiteral("Could not read the project file: %1").arg(file.errorString()));
            return;
        }

        QJsonParseError parseError;
        const QJsonDocument document = QJsonDocument::fromJson(file.readAll(), &parseError);
        if (parseError.error != QJsonParseError::NoError || !document.isObject()) {
            setError(QStringLiteral("The project file is invalid JSON."));
            return;
        }

        const QJsonObject root = document.object();
        bool seedValid = false;
        candidateSeed = root.value(QStringLiteral("seed")).toString().toULongLong(&seedValid);
        if (root.value(QStringLiteral("formatVersion")).toInt(-1) != projectFormatVersion
            || root.value(QStringLiteral("starCount")).toInt(-1) != galaxyStarCount
            || !seedValid
            || !root.value(QStringLiteral("systems")).isArray()) {
            setError(QStringLiteral("This folder contains an unsupported or incomplete project."));
            return;
        }

        const QJsonArray systems = root.value(QStringLiteral("systems")).toArray();
        for (const QJsonValue &value : systems) {
            if (!value.isObject()) {
                setError(QStringLiteral("The project contains an invalid system entry."));
                return;
            }
            const QJsonObject system = value.toObject();
            const int starIndex = system.value(QStringLiteral("starIndex")).toInt(-1);
            const QString name = system.value(QStringLiteral("name")).toString().trimmed();
            if (starIndex < 0 || starIndex >= galaxyStarCount || name.isEmpty()
                || name.size() > 80
                || candidateSystems.contains(starIndex)) {
                setError(QStringLiteral("The project contains an invalid or duplicate system."));
                return;
            }
            candidateSystems.insert(starIndex, name);
        }
    } else if (!writeProject(filePath, candidateSeed, candidateSystems)) {
        return;
    }

    projectDirectory_ = selectedPath;
    seed_ = candidateSeed;
    starCount_ = galaxyStarCount;
    systems_ = candidateSystems;
    setError(QString());
    emit projectDirectoryChanged();
    emit projectDataChanged();
}

bool ProjectStore::addSystem(int starIndex, const QString &name)
{
    const QString systemName = name.trimmed();
    if (projectDirectory_.isEmpty()) {
        setError(QStringLiteral("Choose a project folder before saving a system."));
        return false;
    }
    if (starIndex < 0 || starIndex >= starCount_) {
        setError(QStringLiteral("Select a star before creating a system."));
        return false;
    }
    if (systemName.isEmpty() || systemName.size() > 80) {
        setError(QStringLiteral("System names must be between 1 and 80 characters."));
        return false;
    }
    if (systems_.contains(starIndex)) {
        setError(QStringLiteral("A system is already saved for this star."));
        return false;
    }

    QHash<int, QString> updatedSystems = systems_;
    updatedSystems.insert(starIndex, systemName);
    const QString filePath = QDir(projectDirectory_).filePath(projectFileName);
    if (!writeProject(filePath, seed_, updatedSystems))
        return false;

    systems_ = updatedSystems;
    setError(QString());
    emit projectDataChanged();
    return true;
}

bool ProjectStore::writeProject(const QString &path, quint64 seed,
                                const QHash<int, QString> &systems)
{
    QJsonArray savedSystems;
    for (auto it = systems.cbegin(); it != systems.cend(); ++it) {
        QJsonObject system;
        system.insert(QStringLiteral("starIndex"), it.key());
        system.insert(QStringLiteral("name"), it.value());
        savedSystems.append(system);
    }

    QJsonObject root;
    root.insert(QStringLiteral("formatVersion"), projectFormatVersion);
    root.insert(QStringLiteral("seed"), QString::number(seed));
    root.insert(QStringLiteral("starCount"), galaxyStarCount);
    root.insert(QStringLiteral("systems"), savedSystems);

    QSaveFile file(path);
    if (!file.open(QIODevice::WriteOnly)) {
        setError(QStringLiteral("Could not save the project file: %1").arg(file.errorString()));
        return false;
    }
    const QByteArray contents = QJsonDocument(root).toJson(QJsonDocument::Indented);
    if (file.write(contents) != contents.size()) {
        setError(QStringLiteral("Could not write the project file: %1").arg(file.errorString()));
        file.cancelWriting();
        return false;
    }
    if (!file.commit()) {
        setError(QStringLiteral("Could not finish saving the project file: %1")
                     .arg(file.errorString()));
        return false;
    }
    return true;
}

void ProjectStore::setError(const QString &message)
{
    if (lastError_ == message)
        return;
    lastError_ = message;
    emit lastErrorChanged();
}
