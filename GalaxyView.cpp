#include "GalaxyView.h"

#include <QLineF>
#include <QMouseEvent>
#include <QDebug>
#include <QOpenGLBuffer>
#include <QOpenGLFramebufferObject>
#include <QOpenGLFunctions_3_3_Core>
#include <QOpenGLShaderProgram>
#include <QOpenGLVertexArrayObject>
#include <QRandomGenerator>
#include <QWheelEvent>
#include <QVector2D>
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <vector>

namespace {

constexpr int pickGridColumns = 128;
constexpr int pickGridRows = 80;
constexpr float pickGridMinX = -1.05F;
constexpr float pickGridMaxX = 1.05F;
constexpr float pickGridMinY = -0.70F;
constexpr float pickGridMaxY = 0.70F;

quint64 mixBits(quint64 value)
{
    value = (value ^ (value >> 30)) * 0xbf58476d1ce4e5b9ULL;
    value = (value ^ (value >> 27)) * 0x94d049bb133111ebULL;
    return value ^ (value >> 31);
}

float randomUnit(quint64 &state)
{
    state ^= state >> 12;
    state ^= state << 25;
    state ^= state >> 27;
    return static_cast<float>(state >> 40) * (1.0F / 16777216.0F);
}

StarVertex makeStar(int index, quint64 seed)
{
    constexpr float twoPi = 6.28318530718F;
    constexpr int armCount = 4;
    const quint64 starIndex = static_cast<quint64>(index);
    quint64 randomState = mixBits(seed + starIndex * 0x9e3779b97f4a7c15ULL);
    if (randomState == 0)
        randomState = 1;
    const float radius = std::pow(randomUnit(randomState), 0.68F);
    float theta;
    if (randomUnit(randomState) < 0.76F) {
        const int arm = static_cast<int>(randomUnit(randomState) * armCount);
        const float spreadA = randomUnit(randomState);
        const float spreadB = randomUnit(randomState);
        const float noise = (spreadA + spreadB - 1.0F) * 2.45F;
        theta = static_cast<float>(arm) * (twoPi / armCount)
              + radius * 7.4F
              + noise * (0.035F + radius * 0.075F);
    } else {
        theta = randomUnit(randomState) * twoPi;
    }

    const float radialJitterA = randomUnit(randomState);
    const float radialJitterB = randomUnit(randomState);
    const float radialJitter = (radialJitterA + radialJitterB - 1.0F) * 0.012F;
    const float r = std::clamp(radius + radialJitter, 0.0F, 1.08F);
    const float centerGlow = 1.0F - std::min(radius, 1.0F);
    const float size = 0.75F + randomUnit(randomState) * 0.9F
                     + centerGlow * 0.65F;
    return {
        std::cos(theta) * r * 0.94F,
        std::sin(theta) * r * 0.61F,
        size,
        randomUnit(randomState)
    };
}

class GalaxyRenderer final : public QQuickFramebufferObject::Renderer,
                             protected QOpenGLFunctions_3_3_Core
{
public:
    ~GalaxyRenderer() override
    {
        vao_.destroy();
        vbo_.destroy();
    }

    void render() override
    {
        if (!initialized_ && !initialize())
            return;

        if (bufferDirty_)
            uploadStars();

        glViewport(0, 0, framebufferObject()->width(), framebufferObject()->height());
        glDisable(GL_DEPTH_TEST);
        glEnable(GL_PROGRAM_POINT_SIZE);
        glEnable(GL_BLEND);
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        glClearColor(0.018F, 0.029F, 0.048F, 1.0F);
        glClear(GL_COLOR_BUFFER_BIT);

        if (stars_.empty())
            return;

        const float aspect = framebufferObject()->height() > 0
            ? static_cast<float>(framebufferObject()->width())
                / static_cast<float>(framebufferObject()->height())
            : 1.0F;

        program_.bind();
        program_.setUniformValue("uZoom", static_cast<float>(zoom_));
        program_.setUniformValue("uAspect", aspect);
        program_.setUniformValue("uPan", QVector2D(static_cast<float>(pan_.x()),
                                                   static_cast<float>(pan_.y())));
        program_.setUniformValue("uHighlight", 0.0F);
        vao_.bind();
        glDrawArrays(GL_POINTS, 0, static_cast<GLsizei>(stars_.size()));

        if (selectedStarIndex_ >= 0
            && selectedStarIndex_ < static_cast<int>(stars_.size())) {
            program_.setUniformValue("uHighlight", 1.0F);
            glDrawArrays(GL_POINTS, selectedStarIndex_, 1);
        }

        vao_.release();
        program_.release();
        glDisable(GL_BLEND);
    }

    QOpenGLFramebufferObject *createFramebufferObject(const QSize &size) override
    {
        QOpenGLFramebufferObjectFormat format;
        format.setAttachment(QOpenGLFramebufferObject::NoAttachment);
        format.setInternalTextureFormat(GL_RGBA8);
        return new QOpenGLFramebufferObject(size, format);
    }

    void synchronize(QQuickFramebufferObject *item) override
    {
        auto *view = static_cast<GalaxyView *>(item);
        const quint64 seed = view->seed().toULongLong();
        const int count = view->starCount();

        if (seed != seed_ || count != starCount_) {
            seed_ = seed;
            starCount_ = count;
            generateStars();
            bufferDirty_ = true;
        }

        zoom_ = view->zoom();
        pan_ = view->pan();
        selectedStarIndex_ = view->selectedStarIndex();
    }

private:
    bool initialize()
    {
        if (!initializeOpenGLFunctions()) {
            qWarning("Could not initialize OpenGL 3.3 functions for the galaxy renderer.");
            return false;
        }

        static const char *vertexShader = R"(
            #version 330 core
            layout(location = 0) in vec2 aPosition;
            layout(location = 1) in float aSize;
            layout(location = 2) in float aTemperature;
            uniform float uZoom;
            uniform float uAspect;
            uniform vec2 uPan;
            uniform float uHighlight;
            out float vTemperature;
            void main()
            {
                vec2 position = vec2(
                    (aPosition.x * uZoom / uAspect) + uPan.x,
                    (aPosition.y * uZoom) + uPan.y
                );
                gl_Position = vec4(position, 0.0, 1.0);
                gl_PointSize = uHighlight > 0.5
                    ? 15.0
                    : clamp(aSize * sqrt(uZoom), 0.8, 2.8);
                vTemperature = aTemperature;
            }
        )";

        static const char *fragmentShader = R"(
            #version 330 core
            in float vTemperature;
            uniform float uHighlight;
            out vec4 fragmentColor;
            void main()
            {
                float radius = length(gl_PointCoord - vec2(0.5));
                if (uHighlight > 0.5) {
                    float ring = smoothstep(0.24, 0.32, radius)
                               * (1.0 - smoothstep(0.36, 0.44, radius));
                    float glow = 0.2 * exp(-radius * radius * 9.0);
                    fragmentColor = vec4(0.33, 0.91, 1.0, max(ring, glow));
                    return;
                }

                float alpha = (1.0 - smoothstep(0.2, 0.5, radius)) * 0.88;
                vec3 cool = vec3(0.38, 0.68, 1.0);
                vec3 hot = vec3(0.88, 0.96, 1.0);
                fragmentColor = vec4(mix(cool, hot, vTemperature), alpha);
            }
        )";

        if (!program_.addShaderFromSourceCode(QOpenGLShader::Vertex, vertexShader)
            || !program_.addShaderFromSourceCode(QOpenGLShader::Fragment, fragmentShader)
            || !program_.link()) {
            qWarning("Galaxy shader initialization failed: %s",
                     qPrintable(program_.log()));
            return false;
        }

        vbo_.setUsagePattern(QOpenGLBuffer::StaticDraw);
        if (!vbo_.create() || !vao_.create()) {
            qWarning("Could not create OpenGL buffers for the galaxy renderer.");
            return false;
        }

        vao_.bind();
        vbo_.bind();
        program_.bind();
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, sizeof(StarVertex),
                              reinterpret_cast<const void *>(offsetof(StarVertex, x)));
        glEnableVertexAttribArray(1);
        glVertexAttribPointer(1, 1, GL_FLOAT, GL_FALSE, sizeof(StarVertex),
                              reinterpret_cast<const void *>(offsetof(StarVertex, size)));
        glEnableVertexAttribArray(2);
        glVertexAttribPointer(2, 1, GL_FLOAT, GL_FALSE, sizeof(StarVertex),
                              reinterpret_cast<const void *>(offsetof(StarVertex, temperature)));
        program_.release();
        vbo_.release();
        vao_.release();

        initialized_ = true;
        return true;
    }

    void generateStars()
    {
        stars_.clear();
        stars_.reserve(static_cast<std::size_t>(starCount_));
        for (int i = 0; i < starCount_; ++i) {
            stars_.push_back(makeStar(i, seed_));
        }
    }

    void uploadStars()
    {
        if (!initialized_ || !bufferDirty_)
            return;
        if (!vbo_.bind()) {
            qWarning("Could not bind the galaxy star buffer.");
            return;
        }
        const auto byteCount = static_cast<int>(stars_.size() * sizeof(StarVertex));
        vbo_.allocate(stars_.data(), byteCount);
        vbo_.release();
        bufferDirty_ = false;
    }

    QOpenGLShaderProgram program_;
    QOpenGLBuffer vbo_{QOpenGLBuffer::VertexBuffer};
    QOpenGLVertexArrayObject vao_;
    std::vector<StarVertex> stars_;
    quint64 seed_ = 0;
    int starCount_ = 0;
    int selectedStarIndex_ = -1;
    qreal zoom_ = 1.0;
    QPointF pan_;
    bool initialized_ = false;
    bool bufferDirty_ = true;
};

} // namespace

GalaxyView::GalaxyView(QQuickItem *parent)
    : QQuickFramebufferObject(parent)
{
    setAcceptedMouseButtons(Qt::LeftButton);
    setAcceptHoverEvents(true);
    setSeed(QString::number(QRandomGenerator::global()->generate64()));
}

QQuickFramebufferObject::Renderer *GalaxyView::createRenderer() const
{
    return new GalaxyRenderer;
}

QString GalaxyView::seed() const
{
    return QString::number(seedValue_);
}

void GalaxyView::setSeed(const QString &seed)
{
    bool valid = false;
    const quint64 value = seed.toULongLong(&valid);
    if (!valid || value == seedValue_)
        return;
    seedValue_ = value;
    pickIndexBuilt_ = false;
    setSelectedStarIndex(-1);
    emit seedChanged();
    update();
}

int GalaxyView::starCount() const
{
    return starCount_;
}

void GalaxyView::setStarCount(int count)
{
    const int safeCount = std::clamp(count, 1, 5000000);
    if (safeCount == starCount_)
        return;
    starCount_ = safeCount;
    pickIndexBuilt_ = false;
    emit starCountChanged();
    update();
}

int GalaxyView::selectedStarIndex() const
{
    return selectedStarIndex_;
}

qreal GalaxyView::zoom() const
{
    return zoom_;
}

QPointF GalaxyView::pan() const
{
    return pan_;
}

void GalaxyView::mousePressEvent(QMouseEvent *event)
{
    if (event->button() != Qt::LeftButton) {
        event->ignore();
        return;
    }

    pressed_ = true;
    dragging_ = false;
    pressPosition_ = event->position();
    lastPosition_ = pressPosition_;
    event->accept();
}

void GalaxyView::mouseMoveEvent(QMouseEvent *event)
{
    if (!pressed_) {
        event->ignore();
        return;
    }

    const QPointF position = event->position();
    if (!dragging_ && QLineF(pressPosition_, position).length() > 3.0)
        dragging_ = true;

    if (dragging_ && width() > 0.0 && height() > 0.0) {
        pan_.rx() += 2.0 * (position.x() - lastPosition_.x()) / width();
        pan_.ry() -= 2.0 * (position.y() - lastPosition_.y()) / height();
        emit viewChanged();
        update();
    }

    lastPosition_ = position;
    event->accept();
}

void GalaxyView::mouseReleaseEvent(QMouseEvent *event)
{
    if (event->button() != Qt::LeftButton || !pressed_) {
        event->ignore();
        return;
    }

    pressed_ = false;
    if (!dragging_) {
        const int starIndex = findStarAt(event->position());
        setSelectedStarIndex(starIndex);
        if (starIndex >= 0)
            emit starClicked(starIndex);
    }
    event->accept();
}

void GalaxyView::wheelEvent(QWheelEvent *event)
{
    const qreal factor = std::pow(1.0015, event->angleDelta().y());
    zoom_ = std::clamp(zoom_ * factor, 0.65, 24.0);
    emit viewChanged();
    update();
    event->accept();
}

void GalaxyView::ensurePickIndex() const
{
    if (pickIndexBuilt_)
        return;

    pickStars_.clear();
    pickStars_.reserve(static_cast<std::size_t>(starCount_));
    pickBuckets_.clear();
    pickBuckets_.resize(pickGridColumns * pickGridRows);

    for (int index = 0; index < starCount_; ++index) {
        const StarVertex star = makeStar(index, seedValue_);
        pickStars_.push_back(star);
        const int column = std::clamp(
            static_cast<int>((star.x - pickGridMinX) / (pickGridMaxX - pickGridMinX)
                             * pickGridColumns),
            0, pickGridColumns - 1);
        const int row = std::clamp(
            static_cast<int>((star.y - pickGridMinY) / (pickGridMaxY - pickGridMinY)
                             * pickGridRows),
            0, pickGridRows - 1);
        pickBuckets_[row * pickGridColumns + column].push_back(index);
    }

    pickIndexBuilt_ = true;
}

int GalaxyView::findStarAt(const QPointF &position) const
{
    if (width() <= 0.0 || height() <= 0.0)
        return -1;

    ensurePickIndex();
    const qreal aspect = width() / height();
    const qreal cursorX = 2.0 * position.x() / width() - 1.0;
    const qreal cursorY = 1.0 - 2.0 * position.y() / height();
    const qreal worldX = (cursorX - pan_.x()) * aspect / zoom_;
    const qreal worldY = (cursorY - pan_.y()) / zoom_;
    const qreal radiusX = 22.0 * aspect / (width() * zoom_);
    const qreal radiusY = 22.0 / (height() * zoom_);
    if (worldX + radiusX < pickGridMinX || worldX - radiusX > pickGridMaxX
        || worldY + radiusY < pickGridMinY || worldY - radiusY > pickGridMaxY) {
        return -1;
    }

    const auto toColumn = [](qreal x) {
        return std::clamp(
            static_cast<int>((x - pickGridMinX) / (pickGridMaxX - pickGridMinX)
                             * pickGridColumns),
            0, pickGridColumns - 1);
    };
    const auto toRow = [](qreal y) {
        return std::clamp(
            static_cast<int>((y - pickGridMinY) / (pickGridMaxY - pickGridMinY)
                             * pickGridRows),
            0, pickGridRows - 1);
    };
    const int firstColumn = toColumn(worldX - radiusX);
    const int lastColumn = toColumn(worldX + radiusX);
    const int firstRow = toRow(worldY - radiusY);
    const int lastRow = toRow(worldY + radiusY);

    int nearestIndex = -1;
    qreal nearestDistance = 11.0 * 11.0;
    for (int row = firstRow; row <= lastRow; ++row) {
        for (int column = firstColumn; column <= lastColumn; ++column) {
            const auto &bucket = pickBuckets_[row * pickGridColumns + column];
            for (const int index : bucket) {
                const StarVertex &star = pickStars_[static_cast<std::size_t>(index)];
                const qreal screenX = ((star.x * zoom_ / aspect) + pan_.x() + 1.0)
                                    * width() / 2.0;
                const qreal screenY = (1.0 - (star.y * zoom_ + pan_.y()))
                                    * height() / 2.0;
                const qreal dx = screenX - position.x();
                const qreal dy = screenY - position.y();
                const qreal distance = dx * dx + dy * dy;
                if (distance < nearestDistance) {
                    nearestDistance = distance;
                    nearestIndex = index;
                }
            }
        }
    }

    return nearestIndex;
}

void GalaxyView::setSelectedStarIndex(int starIndex)
{
    if (selectedStarIndex_ == starIndex)
        return;
    selectedStarIndex_ = starIndex;
    emit selectedStarChanged();
    update();
}
