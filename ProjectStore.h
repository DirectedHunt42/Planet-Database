#pragma once

#include <QObject>
#include <QHash>
#include <QString>
#include <QVariantMap>

class ProjectStore final : public QObject
{
    Q_OBJECT
    Q_PROPERTY(QString projectDirectory READ projectDirectory NOTIFY projectDirectoryChanged)
    Q_PROPERTY(QString seed READ seed NOTIFY projectDataChanged)
    Q_PROPERTY(int starCount READ starCount CONSTANT)
    Q_PROPERTY(QString lastError READ lastError NOTIFY lastErrorChanged)
    Q_PROPERTY(QVariantMap systems READ systems NOTIFY projectDataChanged)

public:
    explicit ProjectStore(QObject *parent = nullptr);

    QString projectDirectory() const;
    QString seed() const;
    int starCount() const;
    QString lastError() const;
    QVariantMap systems() const;

    Q_INVOKABLE void chooseProjectFolder();
    Q_INVOKABLE bool addSystem(int starIndex, const QString &name);

signals:
    void projectDirectoryChanged();
    void projectDataChanged();
    void lastErrorChanged();

private:
    bool openProjectFolder(const QString &path);
    void rememberProjectFolder(const QString &path);
    void clearRememberedProjectFolder();
    bool writeProject(const QString &path, quint64 seed,
                      const QHash<int, QString> &systems);
    void setError(const QString &message);

    QString projectDirectory_;
    QString settingsFilePath_;
    QString lastError_;
    quint64 seed_ = 1;
    int starCount_ = 1000000;
    QHash<int, QString> systems_;
};
