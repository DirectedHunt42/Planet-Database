#pragma once

#include <QQuickFramebufferObject>
#include <QPointF>
#include <QString>
#include <QtQml/qqmlregistration.h>
#include <vector>

struct StarVertex
{
    float x;
    float y;
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

public:
    explicit GalaxyView(QQuickItem *parent = nullptr);

    Renderer *createRenderer() const override;

    QString seed() const;
    void setSeed(const QString &seed);

    int starCount() const;
    void setStarCount(int count);

    int selectedStarIndex() const;
    qreal zoom() const;
    QPointF pan() const;

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
    int findStarAt(const QPointF &position) const;
    void setSelectedStarIndex(int starIndex);

    quint64 seedValue_ = 1;
    int starCount_ = 1000000;
    int selectedStarIndex_ = -1;
    qreal zoom_ = 1.0;
    QPointF pan_;
    QPointF pressPosition_;
    QPointF lastPosition_;
    bool pressed_ = false;
    bool dragging_ = false;
    mutable bool pickIndexBuilt_ = false;
    mutable std::vector<StarVertex> pickStars_;
    mutable std::vector<std::vector<int>> pickBuckets_;
};
