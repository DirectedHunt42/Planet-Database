#pragma once

#include <QQuickFramebufferObject>
#include <QMatrix4x4>
#include <QMouseEvent>
#include <QPointF>
#include <QWheelEvent>
#include <QString>
#include <QVector3D>
#include <QtQml/qqmlregistration.h>
#include <vector>

struct StarVertex
{
    float x;
    float y;
    float z;
    float size;
    float temperature;
};

class GalaxyView final : public QQuickFramebufferObject
{
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(QString seed READ seed WRITE setSeed NOTIFY seedChanged)
    Q_PROPERTY(int starCount READ starCount WRITE setStarCount NOTIFY starCountChanged)
    Q_PROPERTY(int selectedStarIndex READ selectedStarIndex NOTIFY selectedStarChanged)
    Q_PROPERTY(qreal zoom READ zoom NOTIFY viewChanged)
    Q_PROPERTY(QString sectorCenter READ sectorCenter NOTIFY viewChanged)
    Q_PROPERTY(qreal sectorSize READ sectorSize CONSTANT)

public:
    explicit GalaxyView(QQuickItem *parent = nullptr);

    Renderer *createRenderer() const override;

    QString seed() const;
    void setSeed(const QString &seed);

    int starCount() const;
    void setStarCount(int count);

    int selectedStarIndex() const;
    qreal zoom() const;
    QString sectorCenter() const;
    qreal sectorSize() const;
    QMatrix4x4 viewProjection(float aspectRatio) const;
    QVector3D sectorCenterVector() const;

signals:
    void seedChanged();
    void starCountChanged();
    void starClicked(int starIndex);
    void selectedStarChanged();
    void viewChanged();

protected:
    void mousePressEvent(QMouseEvent *event) override;
    void mouseMoveEvent(QMouseEvent *event) override;
    void mouseReleaseEvent(QMouseEvent *event) override;
    void wheelEvent(QWheelEvent *event) override;

private:
    void ensurePickIndex() const;
    void panSector(const QPointF &delta);
    int findStarAt(const QPointF &position) const;
    void setSelectedStarIndex(int starIndex);

    static constexpr int gridColumns_ = 64;
    static constexpr int gridRows_ = 64;
    static constexpr int gridLayers_ = 16;
    static constexpr qreal sectorHalfSize_ = 0.235;

    quint64 seedValue_ = 1;
    int starCount_ = 1000000;
    int selectedStarIndex_ = -1;
    qreal cameraDistance_ = 3.2;
    qreal yawDegrees_ = 0.0;
    qreal pitchDegrees_ = 42.0;
    QVector3D sectorCenter_;
    QPointF pressPosition_;
    QPointF lastPosition_;
    bool pressed_ = false;
    bool dragging_ = false;
    Qt::MouseButton dragButton_ = Qt::NoButton;
    mutable bool pickIndexBuilt_ = false;
    mutable std::vector<StarVertex> pickStars_;
    mutable std::vector<std::vector<int>> pickBuckets_ =
        std::vector<std::vector<int>>(gridColumns_ * gridRows_ * gridLayers_);
};
