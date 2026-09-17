package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"time"

	"doubletake/internal/airplay"
)

func main() {
	target := flag.String("target", "192.168.0.6", "AirPlay receiver address")
	port := flag.Int("port", 7000, "AirPlay receiver port")
	code := flag.String("code", "", "PIN shown on the receiver")
	flag.Parse()
	c := airplay.NewAirPlayClient(*target, *port)
	defer c.Close()
	if err := c.Connect(context.Background()); err != nil {
		panic(err)
	}
	info, err := c.GetInfo()
	if err != nil {
		panic(err)
	}
	fmt.Printf("info model=%s features=%x\n", info.Model, info.Features)
	setupCtx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	pin := *code
	if pin == "" {
		if err := c.StartPINDisplay(); err != nil {
			panic(err)
		}
		fmt.Print("PIN: ")
		if _, err := fmt.Scanln(&pin); err != nil {
			panic(err)
		}
	}
	if err := c.Pair(setupCtx, pin); err != nil {
		panic(err)
	}
	fmt.Printf("pair ok protocol=%v\n", c.PairingProtocol())
	if err := c.FairPlaySetup(setupCtx); err != nil {
		panic(err)
	}
	session, err := c.SetupMirror(setupCtx, airplay.StreamConfig{FPS: 30, VideoCodec: airplay.VideoCodecH264, NoAudio: true})
	if err != nil {
		panic(err)
	}
	defer session.Close()
	fmt.Printf("mirror setup ok data-port=%d\n", session.DataPort)
	capture := airplay.NewFramedVideoCapture(os.Stdin, airplay.VideoCodecH264)
	// Setup has a finite deadline, but the active mirror must remain live
	// until stdin closes or the caller cancels it. Reusing setupCtx here
	// would turn setup latency into an unexplained short stream.
	if err := session.StreamFrames(context.Background(), capture, 0); err != nil {
		fmt.Fprintf(os.Stderr, "streaming failed: %v\n", err)
		os.Exit(1)
	}
}
