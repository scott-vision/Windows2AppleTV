package airplay

import (
    "encoding/binary"
    "fmt"
    "io"
    "time"
)

// NewFramedVideoCapture adapts a length-prefixed Annex-B stream to the same
// timestamp-preserving input used by the normal capture pipeline. Each record
// is uint32 length, int64 UnixNano PTS, then the complete access unit.
func NewFramedVideoCapture(reader io.ReadCloser, codec VideoCodec) *ScreenCapture {
    return &ScreenCapture{
        stdout: reader,
        frames: &framedVideoReader{reader: reader, codec: normalizeVideoCodec(codec)},
        waitCh: make(chan struct{}),
    }
}

type framedVideoReader struct {
    reader io.Reader
    codec  VideoCodec
}

func (r *framedVideoReader) ReadVideoAccessUnit() (VideoAccessUnit, error) {
    var length uint32
    if err := binary.Read(r.reader, binary.LittleEndian, &length); err != nil {
        return VideoAccessUnit{}, err
    }
    var pts int64
    if err := binary.Read(r.reader, binary.LittleEndian, &pts); err != nil {
        return VideoAccessUnit{}, io.ErrUnexpectedEOF
    }
    if length == 0 || length > maxVideoAccessUnitBytes {
        return VideoAccessUnit{}, fmt.Errorf("framed video access unit length %d is invalid", length)
    }
    data := make([]byte, length)
    if _, err := io.ReadFull(r.reader, data); err != nil {
        return VideoAccessUnit{}, io.ErrUnexpectedEOF
    }
    return VideoAccessUnit{AnnexB: data, PTS: time.Unix(0, pts)}, nil
}
