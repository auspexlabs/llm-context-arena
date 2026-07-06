package sample

type Widget struct {
	Speed int
}

func (w Widget) Spin() int {
	return w.Speed
}

func Helper() int {
	return 1
}