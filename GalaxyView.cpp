#include "GalaxyView.h"

#include <QDebug>
#include <QLineF>
#include <QMouseEvent>
#include <QOpenGLBuffer>
#include <QOpenGLFramebufferObject>
#include <QOpenGLFunctions_3_3_Core>
#include <QOpenGLShaderProgram>
#include <QOpenGLVertexArrayObject>
#include <QRandomGenerator>
#include <QWheelEvent>
#include <QVector4D>
#include <QtMath>
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <vector>

namespace {

constexpr float galaxyMinX = -1.05F;
constexpr float galaxyMaxX = 1.05F;
constexpr float galaxyMinY = -1.05F;
constexpr float galaxyMaxY = 1.05F;
constexpr float galaxyMinZ = -0.24F;
constexpr float galaxyMaxZ = 0.24F;
constexpr float galaxyRadius = 0.94F;
constexpr float sectorHalfSize = 0.235F;
constexpr float cameraFovDegrees = 48.0F;

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

    const float jitterA = randomUnit(randomState);
    const float jitterB = randomUnit(randomState);
    const float r = std::clamp(
        radius + (jitterA + jitterB - 1.0F) * 0.012F, 0.0F, 1.08F);
    const float heightA = randomUnit(randomState);
    const float heightB = randomUnit(randomState);
    const float heightC = randomUnit(randomState);
    const float z = (heightA + heightB + heightC - 1.5F) * 0.055F;
    const float centerGlow = 1.0F - std::min(radius, 1.0F);

    return {
        std::cos(theta) * r * galaxyRadius,
        std::sin(theta) * r * galaxyRadius,
        z,
        0.75F + randomUnit(randomState) * 0.9F + centerGlow * 0.65F,
        randomUnit(randomState)
    };
}

int bucketForCoordinate(float value, float minimum, float maximum, int count)
{
    const float scaled = (value - minimum) / (maximum - minimum) * count;
    return std::clamp(static_cast<int>(scaled), 0, count - 1);
}

class GalaxyRenderer final : public QQuickFramebufferObject::Renderer,
                             protected QOpenGLFunctions_3_3_Core
{
public:
    ~GalaxyRenderer() override
    {
        sectorVao_.destroy();
        sectorVbo_.destroy();
        starsVao_.destroy();
        starsVbo_.destroy();
    }

    void render() override
    {
        if (!initialized_ && !initialize())
            return;

        if (bufferDirty_ && !uploadStars())
            return;

        const QSize framebufferSize = framebufferObject()->size();
        glViewport(0, 0, framebufferSize.width(), framebufferSize.height());
        glDisable(GL_SCISSOR_TEST);
        glEnable(GL_DEPTH_TEST);
        glDepthFunc(GL_LEQUAL);
        glEnable(GL_PROGRAM_POINT_SIZE);
        glEnable(GL_BLEND);
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        glDepthMask(GL_TRUE);
        glClearColor(0.018F, 0.029F, 0.048F, 1.0F);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        if (stars_.empty())
            return;

        starProgram_.bind();
        starProgram_.setUniformValue("uViewProjection", viewProjection_);
        starProgram_.setUniformValue("uZoom", static_cast<float>(zoom_));
        starProgram_.setUniformValue("uHighlight", 0.0F);
        starsVao_.bind();
        glDrawArrays(GL_POINTS, 0, static_cast<GLsizei>(stars_.size()));

        if (selectedStarIndex_ >= 0
            && selectedStarIndex_ < static_cast<int>(stars_.size())) {
            starProgram_.setUniformValue("uHighlight", 1.0F);
            glDrawArrays(GL_POINTS, selectedStarIndex_, 1);
        }

        starsVao_.release();
        starProgram_.release();

        drawSectorCube();
        glDisable(GL_BLEND);
        glDisable(GL_DEPTH_TEST);
    }

    QOpenGLFramebufferObject *createFramebufferObject(const QSize &size) override
    {
        QOpenGLFramebufferObjectFormat format;
        format.setAttachment(QOpenGLFramebufferObject::CombinedDepthStencil);
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

        const QSize size = view->size().toSize();
        const float aspect = size.height() > 0
            ? static_cast<float>(size.width()) / static_cast<float>(size.height())
            : 1.0F;
        viewProjection_ = view->viewProjection(aspect);
        zoom_ = view->zoom();
        sectorCenter_ = view->sectorCenterVector();
        selectedStarIndex_ = view->selectedStarIndex();
    }

private:
    bool initialize()
    {
        if (!initializeOpenGLFunctions()) {
            qWarning("Could not initialize OpenGL 3.3 functions for the galaxy renderer.");
            return false;
        }

        static const char *starVertexShader = R"(
            #version 330 core
            layout(location = 0) in vec3 aPosition;
            layout(location = 1) in float aSize;
            layout(location = 2) in float aTemperature;
            uniform mat4 uViewProjection;
            uniform float uZoom;
            uniform float uHighlight;
            out float vTemperature;
            void main()
            {
                gl_Position = uViewProjection * vec4(aPosition, 1.0);
                gl_PointSize = uHighlight > 0.5
                    ? 18.0
                    : clamp(aSize * uZoom, 1.0, 4.0);
                vTemperature = aTemperature;
            }
        )";

        static const char *starFragmentShader = R"(
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
                    float glow = 0.3 * exp(-radius * radius * 9.0);
                    fragmentColor = vec4(0.33, 0.91, 1.0, max(ring, glow));
                    return;
                }

                float alpha = (1.0 - smoothstep(0.2, 0.5, radius)) * 0.88;
                vec3 cool = vec3(0.38, 0.68, 1.0);
                vec3 hot = vec3(0.88, 0.96, 1.0);
                fragmentColor = vec4(mix(cool, hot, vTemperature), alpha);
            }
        )";

        static const char *sectorVertexShader = R"(
            #version 330 core
            layout(location = 0) in vec3 aPosition;
            uniform mat4 uViewProjection;
            void main()
            {
                gl_Position = uViewProjection * vec4(aPosition, 1.0);
            }
        )";

        static const char *sectorFragmentShader = R"(
            #version 330 core
            uniform vec4 uColor;
            out vec4 fragmentColor;
            void main()
            {
                fragmentColor = uColor;
            }
        )";

        if (!starProgram_.addShaderFromSourceCode(
                QOpenGLShader::Vertex, starVertexShader)
            || !starProgram_.addShaderFromSourceCode(
                QOpenGLShader::Fragment, starFragmentShader)
            || !starProgram_.link()) {
            qWarning("Galaxy star shader initialization failed: %s",
                     qPrintable(starProgram_.log()));
            return false;
        }

        if (!sectorProgram_.addShaderFromSourceCode(
                QOpenGLShader::Vertex, sectorVertexShader)
            || !sectorProgram_.addShaderFromSourceCode(
                QOpenGLShader::Fragment, sectorFragmentShader)
            || !sectorProgram_.link()) {
            qWarning("Galaxy sector shader initialization failed: %s",
                     qPrintable(sectorProgram_.log()));
            return false;
        }

        starsVbo_.setUsagePattern(QOpenGLBuffer::StaticDraw);
        sectorVbo_.setUsagePattern(QOpenGLBuffer::DynamicDraw);
        if (!starsVbo_.create() || !starsVao_.create()
            || !sectorVbo_.create() || !sectorVao_.create()) {
            qWarning("Could not create OpenGL buffers for the galaxy renderer.");
            return false;
        }

        starsVao_.bind();
        starsVbo_.bind();
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(StarVertex),
                              reinterpret_cast<const void *>(offsetof(StarVertex, x)));
        glEnableVertexAttribArray(1);
        glVertexAttribPointer(1, 1, GL_FLOAT, GL_FALSE, sizeof(StarVertex),
                              reinterpret_cast<const void *>(offsetof(StarVertex, size)));
        glEnableVertexAttribArray(2);
        glVertexAttribPointer(2, 1, GL_FLOAT, GL_FALSE, sizeof(StarVertex),
                              reinterpret_cast<const void *>(offsetof(StarVertex, temperature)));
        starsVbo_.release();
        starsVao_.release();

        sectorVao_.bind();
        sectorVbo_.bind();
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(QVector3D),
                              nullptr);
        sectorVbo_.release();
        sectorVao_.release();

        initialized_ = true;
        return true;
    }

    void generateStars()
    {
        stars_.clear();
        stars_.reserve(static_cast<std::size_t>(starCount_));
        for (int i = 0; i < starCount_; ++i)
            stars_.push_back(makeStar(i, seed_));
    }

    bool uploadStars()
    {
        if (!starsVbo_.bind()) {
            qWarning("Could not bind the galaxy star buffer.");
            return false;
        }

        const auto byteCount = static_cast<int>(stars_.size() * sizeof(StarVertex));
        starsVbo_.allocate(stars_.data(), byteCount);
        starsVbo_.release();
        bufferDirty_ = false;
        return true;
    }

    void drawSectorCube()
    {
        const float x = sectorCenter_.x();
        const float y = sectorCenter_.y();
        const float z = sectorCenter_.z();
        const QVector3D corners[] = {
            {x - sectorHalfSize, y - sectorHalfSize, z - sectorHalfSize},
            {x + sectorHalfSize, y - sectorHalfSize, z - sectorHalfSize},
            {x + sectorHalfSize, y + sectorHalfSize, z - sectorHalfSize},
            {x - sectorHalfSize, y + sectorHalfSize, z - sectorHalfSize},
            {x - sectorHalfSize, y - sectorHalfSize, z + sectorHalfSize},
            {x + sectorHalfSize, y - sectorHalfSize, z + sectorHalfSize},
            {x + sectorHalfSize, y + sectorHalfSize, z + sectorHalfSize},
            {x - sectorHalfSize, y + sectorHalfSize, z + sectorHalfSize}
        };
        const int edgeCorners[] = {
            0, 1, 1, 2, 2, 3, 3, 0,
            4, 5, 5, 6, 6, 7, 7, 4,
            0, 4, 1, 5, 2, 6, 3, 7
        };
        QVector3D edges[24];
        for (int i = 0; i < 24; ++i)
            edges[i] = corners[edgeCorners[i]];

        sectorVbo_.bind();
        sectorVbo_.allocate(edges, static_cast<int>(sizeof(edges)));
        sectorProgram_.bind();
        sectorProgram_.setUniformValue("uViewProjection", viewProjection_);
        sectorProgram_.setUniformValue("uColor", QVector4D(0.22F, 0.83F, 1.0F, 0.78F));
        sectorVao_.bind();
        glLineWidth(1.0F);
        glDrawArrays(GL_LINES, 0, 24);
        sectorVao_.release();
        sectorProgram_.release();
        sectorVbo_.release();
    }

    QOpenGLShaderProgram starProgram_;
    QOpenGLShaderProgram sectorProgram_;
    QOpenGLBuffer starsVbo_{QOpenGLBuffer::VertexBuffer};
    QOpenGLBuffer sectorVbo_{QOpenGLBuffer::VertexBuffer};
    QOpenGLVertexArrayObject starsVao_;
    QOpenGLVertexArrayObject sectorVao_;
    std::vector<StarVertex> stars_;
    QMatrix4x4 viewProjection_;
    quint64 seed_ = 0;
    int starCount_ = 0;
    int selectedStarIndex_ = -1;
    QVector3D sectorCenter_;
    qreal zoom_ = 1.0;
    bool initialized_ = false;
    bool bufferDirty_ = true;
};

} // namespace

GalaxyView::GalaxyView(QQuickItem *parent)
    : QQuickFramebufferObject(parent),
      sectorCenter_(0.0F, 0.0F, 0.0F)
{
    setAcceptedMouseButtons(Qt::AllButtons);
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
    return 3.2 / cameraDistance_;
}

QString GalaxyView::sectorCenter() const
{
    return QStringLiteral("%1, %2, %3")
        .arg(sectorCenter_.x(), 0, 'f', 2)
        .arg(sectorCenter_.y(), 0, 'f', 2)
        .arg(sectorCenter_.z(), 0, 'f', 2);
}

qreal GalaxyView::sectorSize() const
{
    return sectorHalfSize_ * 2.0;
}

QVector3D GalaxyView::sectorCenterVector() const
{
    return sectorCenter_;
}

QMatrix4x4 GalaxyView::viewProjection(float aspectRatio) const
{
    const float yaw = qDegreesToRadians(static_cast<float>(yawDegrees_));
    const float pitch = qDegreesToRadians(static_cast<float>(pitchDegrees_));
    const QVector3D direction(
        std::sin(yaw) * std::cos(pitch),
        -std::cos(yaw) * std::cos(pitch),
        std::sin(pitch));
    const QVector3D eye = sectorCenter_ + direction * static_cast<float>(cameraDistance_);

    QMatrix4x4 view;
    view.lookAt(eye, sectorCenter_, QVector3D(0.0F, 0.0F, 1.0F));
    QMatrix4x4 projection;
    projection.perspective(cameraFovDegrees, std::max(aspectRatio, 0.01F), 0.025F, 50.0F);
    return projection * view;
}

void GalaxyView::mousePressEvent(QMouseEvent *event)
{
    if (event->button() != Qt::LeftButton && event->button() != Qt::RightButton
        && event->button() != Qt::MiddleButton) {
        event->ignore();
        return;
    }

    pressed_ = true;
    dragging_ = false;
    dragButton_ = event->button();
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

    if (dragging_) {
        const QPointF delta = position - lastPosition_;
        if (dragButton_ == Qt::LeftButton) {
            yawDegrees_ = std::fmod(yawDegrees_ - delta.x() * 0.35, 360.0);
            pitchDegrees_ = std::clamp(pitchDegrees_ + delta.y() * 0.30, 8.0, 82.0);
            emit viewChanged();
            update();
        } else {
            panSector(delta);
        }
    }

    lastPosition_ = position;
    event->accept();
}

void GalaxyView::mouseReleaseEvent(QMouseEvent *event)
{
    if (event->button() != dragButton_ || !pressed_) {
        event->ignore();
        return;
    }

    pressed_ = false;
    if (!dragging_ && dragButton_ == Qt::LeftButton) {
        const int starIndex = findStarAt(event->position());
        setSelectedStarIndex(starIndex);
        if (starIndex >= 0)
            emit starClicked(starIndex);
    }
    dragButton_ = Qt::NoButton;
    event->accept();
}

void GalaxyView::wheelEvent(QWheelEvent *event)
{
    const qreal factor = std::pow(1.0015, event->angleDelta().y());
    cameraDistance_ = std::clamp(cameraDistance_ / factor, 0.68, 8.0);
    emit viewChanged();
    update();
    event->accept();
}

void GalaxyView::panSector(const QPointF &delta)
{
    if (height() <= 0.0)
        return;

    const float yaw = qDegreesToRadians(static_cast<float>(yawDegrees_));
    const float pitch = qDegreesToRadians(static_cast<float>(pitchDegrees_));
    const QVector3D right(std::cos(yaw), std::sin(yaw), 0.0F);
    const QVector3D up(-std::sin(yaw) * std::sin(pitch),
                       std::cos(yaw) * std::sin(pitch),
                       std::cos(pitch));
    const float unitsPerPixel = static_cast<float>(
        2.0 * cameraDistance_ * std::tan(qDegreesToRadians(cameraFovDegrees) / 2.0)
        / height());

    sectorCenter_ += right * static_cast<float>(-delta.x() * unitsPerPixel)
                   + up * static_cast<float>(delta.y() * unitsPerPixel);
    const float maxCenterRadius =
        galaxyRadius - sectorHalfSize * std::sqrt(2.0F);
    const float centerRadius = std::hypot(sectorCenter_.x(), sectorCenter_.y());
    if (centerRadius > maxCenterRadius) {
        const float scale = maxCenterRadius / centerRadius;
        sectorCenter_.setX(sectorCenter_.x() * scale);
        sectorCenter_.setY(sectorCenter_.y() * scale);
    }
    sectorCenter_.setZ(std::clamp(sectorCenter_.z(), -0.10F, 0.10F));

    if (selectedStarIndex_ >= 0) {
        const StarVertex &selected = pickStars_[static_cast<std::size_t>(selectedStarIndex_)];
        const float halfSize = static_cast<float>(sectorHalfSize_);
        if (std::abs(selected.x - sectorCenter_.x()) > halfSize
            || std::abs(selected.y - sectorCenter_.y()) > halfSize
            || std::abs(selected.z - sectorCenter_.z()) > halfSize) {
            setSelectedStarIndex(-1);
        }
    }

    emit viewChanged();
    update();
}

void GalaxyView::ensurePickIndex() const
{
    if (pickIndexBuilt_)
        return;

    pickStars_.clear();
    pickStars_.reserve(static_cast<std::size_t>(starCount_));
    for (auto &bucket : pickBuckets_)
        bucket.clear();

    for (int index = 0; index < starCount_; ++index) {
        const StarVertex star = makeStar(index, seedValue_);
        pickStars_.push_back(star);
        const int column = bucketForCoordinate(
            star.x, galaxyMinX, galaxyMaxX, gridColumns_);
        const int row = bucketForCoordinate(
            star.y, galaxyMinY, galaxyMaxY, gridRows_);
        const int layer = bucketForCoordinate(
            star.z, galaxyMinZ, galaxyMaxZ, gridLayers_);
        const int bucketIndex = (layer * gridRows_ + row) * gridColumns_ + column;
        pickBuckets_[static_cast<std::size_t>(bucketIndex)].push_back(index);
    }

    pickIndexBuilt_ = true;
}

int GalaxyView::findStarAt(const QPointF &position) const
{
    if (width() <= 0.0 || height() <= 0.0)
        return -1;

    ensurePickIndex();
    const QMatrix4x4 matrix = viewProjection(
        static_cast<float>(width() / height()));
    const float halfSize = static_cast<float>(sectorHalfSize_);
    const int firstColumn = bucketForCoordinate(
        sectorCenter_.x() - halfSize, galaxyMinX, galaxyMaxX, gridColumns_);
    const int lastColumn = bucketForCoordinate(
        sectorCenter_.x() + halfSize, galaxyMinX, galaxyMaxX, gridColumns_);
    const int firstRow = bucketForCoordinate(
        sectorCenter_.y() - halfSize, galaxyMinY, galaxyMaxY, gridRows_);
    const int lastRow = bucketForCoordinate(
        sectorCenter_.y() + halfSize, galaxyMinY, galaxyMaxY, gridRows_);
    const int firstLayer = bucketForCoordinate(
        sectorCenter_.z() - halfSize, galaxyMinZ, galaxyMaxZ, gridLayers_);
    const int lastLayer = bucketForCoordinate(
        sectorCenter_.z() + halfSize, galaxyMinZ, galaxyMaxZ, gridLayers_);

    int nearestIndex = -1;
    qreal nearestDistance = 13.0 * 13.0;
    float nearestDepth = 1.0F;
    for (int layer = firstLayer; layer <= lastLayer; ++layer) {
        for (int row = firstRow; row <= lastRow; ++row) {
            for (int column = firstColumn; column <= lastColumn; ++column) {
                const int bucketIndex = (layer * gridRows_ + row) * gridColumns_ + column;
                const auto &bucket = pickBuckets_[static_cast<std::size_t>(bucketIndex)];
                for (const int index : bucket) {
                    const StarVertex &star = pickStars_[static_cast<std::size_t>(index)];
                    if (std::abs(star.x - sectorCenter_.x()) > halfSize
                        || std::abs(star.y - sectorCenter_.y()) > halfSize
                        || std::abs(star.z - sectorCenter_.z()) > halfSize) {
                        continue;
                    }

                    const QVector4D clip = matrix * QVector4D(star.x, star.y, star.z, 1.0F);
                    if (clip.w() <= 0.0F)
                        continue;
                    const QVector3D ndc = clip.toVector3DAffine();
                    if (ndc.z() < -1.0F || ndc.z() > 1.0F)
                        continue;

                    const qreal screenX = (ndc.x() + 1.0) * width() / 2.0;
                    const qreal screenY = (1.0 - ndc.y()) * height() / 2.0;
                    const qreal dx = screenX - position.x();
                    const qreal dy = screenY - position.y();
                    const qreal distance = dx * dx + dy * dy;
                    if (distance < nearestDistance
                        || (qFuzzyCompare(distance, nearestDistance)
                            && ndc.z() < nearestDepth)) {
                        nearestDistance = distance;
                        nearestDepth = ndc.z();
                        nearestIndex = index;
                    }
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
