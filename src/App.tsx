import { useState } from 'react'
import './App.css'
import Header from "./components/Header"
import SearchForm from "./components/SearchForm"
import ClassroomList from "./components/ClassroomList"
import type { Classroom } from "./types"

function App() {
  const [selectedDate, setSelectedDate] = useState<string>("")  //選択している日付
  const [selectedClassroom, setSelectedClassroom] = useState<string>("")  //選択している教室
  const [classrooms, setClassrooms] = useState<Classroom[]>([])  //教室の予約・空き教室情報
  const [loading, setLoading] = useState<boolean>(false)  //データ取得中か否か
  const [error, setError] = useState<string>("")  //エラーが発生したかどうか

  return (
    <>
      <Header />
      <SearchForm  selectedDate={selectedDate} setSelectedDate={setSelectedDate} selectedClassroom={selectedClassroom} setSelectedClassroom={setSelectedClassroom} />
      <ClassroomList classrooms={classrooms} />
    </>
  )
}

export default App
