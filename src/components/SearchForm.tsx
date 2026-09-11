import DateSelector from "./DateSelector"
import ClassroomSelector from "./ClassroomSelector"
import type { Dispatch, SetStateAction } from "react"

type Props = {
    selectedDate: string;
    setSelectedDate: Dispatch<SetStateAction<string>>;
    selectedClassroom: string;
    setSelectedClassroom: Dispatch<SetStateAction<string>>;
};

function SearchForm({selectedDate, setSelectedDate, selectedClassroom, setSelectedClassroom}: Props) {
    return (
        <div>
            <DateSelector selectedDate={selectedDate} setSelectedDate={setSelectedDate} />
            <ClassroomSelector selectedClassroom={selectedClassroom} setSelectedClassroom={setSelectedClassroom} />
        </div>
    )
}

export default SearchForm
